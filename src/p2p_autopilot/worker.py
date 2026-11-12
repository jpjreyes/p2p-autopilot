"""One agent run, start to finish: the same code in a thread (local) or as a Cloud Run Job execution (D21).

Run on the portal, record every step (and its screenshot) in Postgres as it happens, then read, check and match the
downloaded invoices and store the review items. A failed run is recorded as an error, never left "running".

Cloud Run Job:  python -m p2p_autopilot.worker   (RUN_ID, PORTAL, CHAOS from the execution's env overrides)
"""

from __future__ import annotations

import json
import os
import urllib.request
from pathlib import Path

from dotenv import load_dotenv

from p2p_autopilot import storage
from p2p_autopilot.agent import run
from p2p_autopilot.llm import get_backend
from p2p_autopilot.orders.store import PostgresOrderSystem, connect
from p2p_autopilot.pipeline import process
from p2p_autopilot.runstore import RunStore

load_dotenv()
PORTAL_BASE = os.environ.get("PORTAL_BASE_URL", "http://127.0.0.1:8061")


def set_chaos(portal: str, modes: list[str]) -> None:
    req = urllib.request.Request(f"{PORTAL_BASE}/admin/chaos", method="POST",
                                 data=json.dumps({"portal": portal, "modes": modes}).encode(),
                                 headers={"Content-Type": "application/json",
                                          "X-Admin-Token": os.environ.get("PORTAL_ADMIN_TOKEN", "dev-admin-token")})
    urllib.request.urlopen(req, timeout=10).read()


def execute(run_id: str, portal: str, chaos: str, conn=None) -> None:
    conn = conn or connect()
    rs = RunStore(conn)
    try:
        set_chaos(portal, [chaos] if chaos else [])

        def on_step(idx, n, action, ok, msg, shot):
            ref = storage.put_file(shot, f"runs/{run_id}/{Path(shot).name}") if shot else ""
            rs.step(run_id, idx, n, action, ok, msg, ref)

        result = run(portal, PORTAL_BASE, get_backend(), run_id=run_id, on_step=on_step)
        calls = sum(1 for s in result.steps if s.tokens_in)
        rs.finish(run_id, result.outcome, result.reason, len(result.downloads), calls, result.seconds)
        if result.downloads:
            items = process(result.run_dir, get_backend(), PostgresOrderSystem(conn))
            for item in items:  # the job's disk is gone after the run: the reviewer's copy goes to storage
                item.pdf = storage.put_file(item.pdf, f"runs/{run_id}/{Path(item.pdf).name}", "application/pdf")
            rs.save_review(run_id, items)
    except Exception as e:  # noqa: BLE001 -- a failed demo run is recorded, never left "running"
        rs.finish(run_id, "error", repr(e)[:300], 0, 0, 0)
    finally:
        try:
            set_chaos(portal, [])
        except OSError:
            pass


if __name__ == "__main__":
    execute(os.environ["RUN_ID"], os.environ["PORTAL"], os.environ.get("CHAOS", ""))
