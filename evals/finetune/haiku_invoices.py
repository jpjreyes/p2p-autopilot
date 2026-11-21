"""Claude (Haiku, on the Claude plan, D23 rules) reads the 92 generated invoice scans with the D26 prompt, so the
cascade has the large model's answers for the documents it escalates. Resumable.

    uv run python evals/finetune/haiku_invoices.py
"""

from __future__ import annotations

import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "evals"))
from real_scans import PROMPT, SCHEMA, SYSTEM, png  # noqa: E402

from p2p_autopilot import subscription  # noqa: E402
from p2p_autopilot.llm import get_backend  # noqa: E402

INV = ROOT / "runs" / "finetune" / "data" / "invoices"
OUT = ROOT / "runs" / "finetune" / "haiku_inv.jsonl"


def main() -> None:
    rows = [json.loads(x) for x in (INV / "invoices.jsonl").read_text().splitlines()]
    done = {json.loads(x)["file"] for x in OUT.read_text().splitlines()} if OUT.exists() else set()
    todo = [r["file"] for r in rows if r["file"] not in done]
    backend, t0 = get_backend(), time.monotonic()
    print(f"{len(done)} saved, {len(todo)} to read", flush=True)

    def read(f):
        res = backend.complete(SYSTEM, PROMPT, SCHEMA, images=[png(INV / "images" / f)])
        return {"file": f, "answer": res.data, "latency_s": round(res.latency_s, 2), "cost_usd": res.cost_usd}

    with ThreadPoolExecutor(4) as pool:
        futs = {pool.submit(read, f): f for f in todo}
        for n, fut in enumerate(as_completed(futs), 1):
            try:
                row = fut.result()
            except subscription.EvalStop:
                pool.shutdown(cancel_futures=True)
                raise
            except RuntimeError as e:
                row = {"file": futs[fut], "answer": None, "error": str(e)[:200], "cost_usd": 0.0}
            with OUT.open("a") as fh:
                fh.write(json.dumps(row) + "\n")
            if n % 10 == 0 or n == len(todo):
                use = subscription.last_limits or {}
                print(f"{n}/{len(todo)} · ETA {int((time.monotonic() - t0) / n * (len(todo) - n))} s · 5h "
                      f"{(use.get('five_hour') or {}).get('utilization')} · week "
                      f"{(use.get('seven_day') or {}).get('utilization')}", flush=True)


if __name__ == "__main__":
    main()
