"""The agent loop: observe the page -> the model picks ONE action -> code executes it -> log the step -> repeat.

Same instructions for every portal: no portal-specific hints, so the held-out portal is a fair test (D1).
The model never sees passwords (placeholders), cannot leave the portal (allowed origin), and has no approve/pay
action at all (C1). It stops on `done`, on `handoff` (CAPTCHA, stuck, anything risky), or at the step budget.

Run:  uv run python -m legacy_portal.agent --portal a
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv
from playwright.sync_api import sync_playwright

from legacy_portal.browser import BrowserTools
from legacy_portal.llm import DEFAULT_MODEL, Backend, get_backend
from legacy_portal.portals.app import CREDENTIALS

RUNS_DIR = Path(__file__).resolve().parents[2] / "runs"

SYSTEM = """You operate a supplier's web portal for an accounts-payable team, one action at a time.
You see each frame's accessibility tree (roles and names of links, buttons, fields, tables).

Address elements exactly as they appear: {"frame": <frame label>, "role": <role>, "name": <accessible name>}.
If several elements share the same role and name (e.g. unlabeled textboxes, many "View" links), add "nth":
their 0-based position in page order.
Actions:
  click     click a link or button
  fill      type into a textbox. For credentials use the placeholders {{username}} and {{password}};
            you never see the real values
  select    choose an option (value = the option's visible label) in a combobox
  download  save the PDF behind a link (use it on the link that opens the document's PDF)
  goto      open a URL on this same portal (value = URL or path)
  done      every in-scope document has been downloaded
  handoff   stop and ask a human: CAPTCHA or "verify you are human", repeated failures, anything unclear or risky

Rules:
- Goal: download the PDF of EVERY OPEN document (invoices and credit notes). Skip documents marked paid.
- Documents can be spread over several pages, months or search results: make sure you have seen all of them.
- Some portals show nothing until you search, or hide details in a pop-up: explore the controls.
- Never guess element names. If an action fails, look at the page again and try something different.
- If the session expires, log in again and continue where you left off.
- Never solve or bypass a CAPTCHA: hand off.
- Reply with JSON: {"actions": [...], "reason": "..."}. You may batch up to 5 actions when you can already see
  every element they need (e.g. open details -> download -> close). Execution stops at the first failure and you
  get to look again. "done" and "handoff" must be the only action in their batch.
- Keep "reason" to one short sentence."""

ONE_ACTION = {
    "type": "object",
    "properties": {
        "action": {"type": "string", "enum": ["click", "fill", "select", "download", "goto", "done", "handoff"]},
        "frame": {"type": "string"},
        "role": {"type": "string"},
        "name": {"type": "string"},
        "value": {"type": "string"},
        "nth": {"type": "integer", "minimum": 0},
    },
    "required": ["action"],
}
MAX_BATCH = 5
ACTION_SCHEMA = {
    "type": "object",
    "properties": {
        "actions": {"type": "array", "items": ONE_ACTION, "minItems": 1, "maxItems": MAX_BATCH},
        "reason": {"type": "string"},
    },
    "required": ["actions", "reason"],
}


@dataclass
class Step:
    n: int
    action: dict
    ok: bool
    result: str
    screenshot: str
    tokens_in: int
    tokens_out: int
    latency_s: float


@dataclass
class RunResult:
    portal: str
    outcome: str  # done | handoff | budget | error
    reason: str
    downloads: list[str]
    steps: list[Step] = field(default_factory=list)
    run_dir: str = ""
    contexts: dict[str, str] = field(default_factory=dict)
    seconds: float = 0.0


def run(portal: str, base_url: str, backend: Backend, model: str = DEFAULT_MODEL, max_steps: int = 60,
        headless: bool = True) -> RunResult:
    run_dir = RUNS_DIR / f"{datetime.now():%Y%m%d-%H%M%S}-{portal}"
    run_dir.mkdir(parents=True, exist_ok=True)
    user, pw = CREDENTIALS[portal]
    history: list[str] = []
    t0 = time.monotonic()
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)
        page = browser.new_page(viewport={"width": 1200, "height": 800})
        tools = BrowserTools(page, base_url, {"username": user, "password": pw}, run_dir)
        page.goto(f"{base_url}/{portal}/login")
        result = RunResult(portal, "budget", "step budget exhausted", tools.downloads, run_dir=str(run_dir))
        for n in range(1, max_steps + 1):
            observation = tools.observe()
            prompt = (f"Step {n}/{max_steps}.\n"
                      f"Downloaded so far ({len(tools.downloads)}): {[Path(d).name for d in tools.downloads]}\n"
                      f"Recent actions:\n" + ("\n".join(history[-15:]) or "(none)") +
                      f"\n\nCurrent page:\n{observation}")
            try:
                llm = backend.complete(SYSTEM, prompt, ACTION_SCHEMA, model=model)
            except (RuntimeError, subprocess.TimeoutExpired, json.JSONDecodeError, KeyError) as e:
                # model or CLI failure: stop safely, never guess
                result.outcome, result.reason = "error", f"model call failed: {e}"
                break
            batch, reason = llm.data["actions"][:MAX_BATCH], llm.data.get("reason", "")
            terminal = next((a for a in batch if a["action"] in ("done", "handoff")), None)
            if terminal:
                shot = tools.screenshot(f"{n:03d}-{terminal['action']}")
                result.steps.append(Step(n, {**terminal, "reason": reason}, True, terminal["action"], shot,
                                         llm.input_tokens, llm.output_tokens, llm.latency_s))
                result.outcome, result.reason = terminal["action"], reason
                break
            for i, action in enumerate(batch):
                res = tools.run(action)
                shot = tools.screenshot(f"{n:03d}-{i}-{action['action']}")
                cost_in, cost_out, lat = (llm.input_tokens, llm.output_tokens, llm.latency_s) if i == 0 else (0, 0, 0)
                result.steps.append(Step(n, {**action, "reason": reason}, res.ok, res.message, shot, cost_in,
                                         cost_out, lat))
                target = f"{action.get('role', '')} {action.get('name', '')!r}".strip()
                nth = f"[{action['nth']}]" if action.get("nth") is not None else ""
                history.append(f"{n}.{i} {action['action']} {target}{nth} -> {'OK' if res.ok else 'FAILED'}: "
                               f"{res.message}")
                print(f"[{portal} {n:02d}.{i}] {action['action']:<8} {(target + nth)[:58]:<58} "
                      f"{'ok ' if res.ok else 'ERR'} {res.message[:70]}", flush=True)
                if not res.ok:
                    break  # look at the page again before doing anything else
            if tools.login_limit_hit:  # enforced in code, not left to the model (C4)
                result.outcome = "handoff"
                result.reason = f"forced: {tools.login_posts} login attempts exceeds the limit (account safety)"
                break
        result.contexts = dict(tools.contexts)
        browser.close()
    result.seconds = round(time.monotonic() - t0, 1)
    (run_dir / "run.json").write_text(json.dumps(asdict(result), indent=2))
    return result


def main():
    load_dotenv()
    ap = argparse.ArgumentParser()
    ap.add_argument("--portal", required=True, choices=["a", "b", "c"])
    ap.add_argument("--max-steps", type=int, default=60)
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--headed", action="store_true")
    args = ap.parse_args()
    if args.portal == "c" and not os.environ.get("LPA_ALLOW_HELD_OUT"):
        raise SystemExit("Portal C is held out (D1). Set LPA_ALLOW_HELD_OUT=1 only for the final eval.")
    base = os.environ.get("PORTAL_BASE_URL", "http://127.0.0.1:8061")
    r = run(args.portal, base, get_backend(), args.model, args.max_steps, headless=not args.headed)
    print(f"\n{r.outcome}: {r.reason}\n{len(r.downloads)} PDFs, {len(r.steps)} steps, {r.seconds}s -> {r.run_dir}")


if __name__ == "__main__":
    main()
