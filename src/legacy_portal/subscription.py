"""Run Claude through the Claude Code CLI (`claude -p`) for local development and evals.

The local backend uses a Claude login instead of an API key; the deployed app uses the API backend. Every call:
  1. runs in a clean, isolated CLI configuration (no user plugins, hooks, settings or memory files), logged in with a
     long-lived CLI token, from an empty working folder;
  2. never bills an API key: API-key variables are removed and the call is rejected unless the CLI reports it is
     using the login (apiKeySource == "none");
  3. stops if any hook runs (the configuration isn't clean);
  4. has a usage guard: after each call the CLI's 5-hour and weekly usage are read, and at or above
     CLAUDE_EVAL_STOP_AT (default 80%) the next call raises QuotaStop, so a long eval stops and can resume later.

Setup:  `claude setup-token`, save the token to ~/.config/claude-eval/oauth_token (chmod 600), and create the empty
folder ~/.config/claude-eval/config. Quick local runs without that setup: CLAUDE_EVAL_ALLOW_DIRTY=1 (normal CLI
configuration; not for reported numbers). The API-key and usage checks still apply.

EvalStop and its subclasses derive from BaseException on purpose: callers that catch Exception/RuntimeError to
retry a task must not swallow "stop the run".
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

HOME = Path(os.environ.get("CLAUDE_EVAL_HOME", Path.home() / ".config" / "claude-eval"))
TOKEN = HOME / "oauth_token"
CONFIG = HOME / "config"
STOP_AT = float(os.environ.get("CLAUDE_EVAL_STOP_AT", "0.80"))
MAX_OUTPUT_TOKENS = "16000"  # same cap as the API backend
_REMOVE = {"ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_BASE_URL", "CLAUDE_CODE_USE_BEDROCK",
           "CLAUDE_CODE_USE_VERTEX", "CLAUDE_CODE_USE_FOUNDRY", "CLAUDE_CODE_OAUTH_TOKEN", "CLAUDE_CONFIG_DIR"}

last_limits: dict | None = None  # latest unifiedWindows seen, shared by every call in this process
_warned = False


class EvalStop(BaseException):
    """Stop the whole run (not a per-task failure)."""


class QuotaStop(EvalStop):
    """The 5-hour or weekly usage window reached the stop threshold."""


class NotClean(EvalStop):
    """The call would not run on the subscription in a clean environment."""


def allow_dirty() -> bool:
    return os.environ.get("CLAUDE_EVAL_ALLOW_DIRTY") == "1"


def clean() -> bool:
    return TOKEN.exists() and CONFIG.is_dir()


def env() -> dict[str, str]:
    e = {k: v for k, v in os.environ.items() if k not in _REMOVE}
    e["CLAUDE_CODE_MAX_OUTPUT_TOKENS"] = MAX_OUTPUT_TOKENS
    if clean():
        e["CLAUDE_CONFIG_DIR"] = str(CONFIG)
        e["CLAUDE_CODE_OAUTH_TOKEN"] = TOKEN.read_text().strip()
    return e


def _utilization(limits: dict | None) -> float:
    return max((w.get("utilization") or 0.0 for w in (limits or {}).values()), default=0.0)


def check_ready() -> None:
    global _warned
    if _utilization(last_limits) >= STOP_AT:
        raise QuotaStop(f"usage at {_utilization(last_limits):.0%} (stop at {STOP_AT:.0%}): {last_limits}")
    if not clean():
        if not allow_dirty():
            raise NotClean(f"clean CLI setup missing ({TOKEN} and empty folder {CONFIG}). Run `claude setup-token`, "
                           "save the token there (chmod 600) and create the folder (see subscription.py). "
                           "For quick local runs only: CLAUDE_EVAL_ALLOW_DIRTY=1.")
        if not _warned:
            print("warning: CLAUDE_EVAL_ALLOW_DIRTY=1 → normal Claude config (plugins/hooks may load); "
                  "not for reported numbers", file=sys.stderr)
            _warned = True


def run(args: list[str], stdin: str | None, timeout: float) -> tuple[subprocess.CompletedProcess, list[dict]]:
    """Run `claude <args> --output-format stream-json --verbose`; return the process and its parsed events."""
    global last_limits
    check_ready()
    cmd = ["claude", *args, "--output-format", "stream-json", "--verbose"]
    with tempfile.TemporaryDirectory(prefix="claude-eval-") as cwd:
        out = subprocess.run(cmd, check=False, input=stdin, capture_output=True, text=True, timeout=timeout,
                             cwd=cwd, env=env())
    events = []
    for line in out.stdout.splitlines():
        if line.strip().startswith("{"):
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    for ev in events:
        t, sub = ev.get("type"), str(ev.get("subtype", ""))
        if t == "system" and sub == "init" and ev.get("apiKeySource") != "none":
            raise NotClean(f"not using the CLI login: apiKeySource={ev.get('apiKeySource')!r}")
        if t == "system" and sub.startswith("hook") and not allow_dirty():
            raise NotClean(f"a hook ran ({ev.get('hook_name') or sub}): the environment is not clean")
        if t == "rate_limit_event":
            info = ev.get("rate_limit_info") or {}
            last_limits = info.get("unifiedWindows") or last_limits
            if info.get("status") == "rejected":
                raise QuotaStop(f"usage limit reached: {info}")
    return out, events
