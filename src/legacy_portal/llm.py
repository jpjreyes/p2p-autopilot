"""Model backends behind one interface (decision D4).

  claude-cli  development: runs `claude -p` on a Claude plan. No tools, no hooks, no MCP, no session
              files, a custom system prompt and JSON-schema-validated output. Not for the live demo.
  anthropic   the API (final evals and live demo); used when ANTHROPIC_API_KEY is set.

Every call returns the parsed JSON plus usage, so evals can report tokens and latency per step.
"""

from __future__ import annotations

import json
import os
import subprocess
import time
from dataclasses import dataclass
from typing import Protocol

DEFAULT_MODEL = os.environ.get("LPA_MODEL", "haiku")


@dataclass
class LLMResult:
    data: dict
    input_tokens: int
    output_tokens: int
    latency_s: float
    model: str


class Backend(Protocol):
    def complete(self, system: str, prompt: str, schema: dict, model: str = DEFAULT_MODEL) -> LLMResult: ...


class ClaudeCLIBackend:
    def __init__(self, timeout_s: int = 120):
        self.timeout_s = timeout_s

    def complete(self, system: str, prompt: str, schema: dict, model: str = DEFAULT_MODEL) -> LLMResult:
        cmd = ["claude", "-p", prompt, "--model", model, "--system-prompt", system,
               "--tools", "", "--setting-sources", "", "--strict-mcp-config", "--disable-slash-commands",
               "--no-session-persistence", "--output-format", "json", "--json-schema", json.dumps(schema)]
        t0 = time.monotonic()
        out = subprocess.run(cmd, check=False, capture_output=True, text=True, timeout=self.timeout_s, cwd="/tmp")
        latency = time.monotonic() - t0
        if out.returncode != 0:
            raise RuntimeError(f"claude CLI failed ({out.returncode}): {out.stderr[-500:] or out.stdout[-500:]}")
        payload = json.loads(out.stdout)
        if payload.get("is_error"):
            raise RuntimeError(f"claude CLI error: {payload.get('result')}")
        data = payload.get("structured_output") or json.loads(payload["result"])
        u = payload.get("usage", {})
        tokens_in = u.get("input_tokens", 0) + u.get("cache_creation_input_tokens", 0) + u.get(
            "cache_read_input_tokens", 0)
        return LLMResult(data, tokens_in, u.get("output_tokens", 0), latency, model)


def get_backend(name: str | None = None) -> Backend:
    name = name or os.environ.get("LPA_BACKEND", "claude-cli")
    if name == "claude-cli":
        return ClaudeCLIBackend()
    raise ValueError(f"unknown backend {name!r} (the 'anthropic' backend arrives with the API key)")
