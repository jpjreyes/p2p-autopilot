"""API for the review console: start a run, watch it live, review the results.

  POST /api/runs                     start an agent run in the background {portal, chaos}
  GET  /api/runs                     recent runs
  GET  /api/runs/{id}                one run with its steps (live while running)
  GET  /api/runs/{id}/steps/{idx}.png  the screenshot of a step (audit log)
  GET  /api/review?status=...        review items
  GET  /api/review/{item_id}         one item with what the agent read and the PO + goods receipt it was matched to
  GET  /api/review/{item_id}/page.png  the invoice's first page, as the reviewer sees it
  POST /api/review/{item_id}         a human decision {decision: approve|reject, note}
  GET  /api/process/...              the process warehouse: overview, payment-block worklist, weekly brief

Guardrails for a public demo: one run at a time, a per-hour run limit, only the dev portals (never the
held-out one), and no endpoint that pays anything.

Run:  uv run uvicorn legacy_portal.api:app --port 8062
"""

from __future__ import annotations

import io
import os
import threading
from collections.abc import Iterator
from contextlib import asynccontextmanager, contextmanager
from datetime import datetime

import pypdfium2 as pdfium
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool
from pydantic import BaseModel

from legacy_portal import storage
from legacy_portal.agent import RUNS_DIR
from legacy_portal.orders.store import PostgresOrderSystem
from legacy_portal.process.api import router as process_router
from legacy_portal.runstore import RunStore, ensure_schema, jsonable
from legacy_portal.worker import execute

load_dotenv()
PORTAL_BASE = os.environ.get("PORTAL_BASE_URL", "http://127.0.0.1:8061")
RUNS_PER_HOUR = int(os.environ.get("LPA_RUNS_PER_HOUR", "6"))
ALLOWED_PORTALS = {"a", "b", "c"}  # D is held out (D10): never runnable from the console
CHAOS_MODES = {"", "layout_variant", "renamed_fields", "session_expiry", "slow", "captcha", "icon_links",
               "opaque_icons", "injection", "scanned", "handwritten"}

POOL = ConnectionPool(os.environ["DATABASE_URL"], min_size=1, max_size=6, open=False,
                      kwargs={"autocommit": True, "row_factory": dict_row})


@asynccontextmanager
async def lifespan(_app):
    POOL.open(wait=True)
    with POOL.connection() as conn:
        ensure_schema(conn)
    yield
    POOL.close()


app = FastAPI(title="Legacy Portal Agent API", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=os.environ.get("CONSOLE_ORIGINS", "http://localhost:3061").split(","),
                   allow_methods=["GET", "POST"], allow_headers=["*"])

_lock = threading.Lock()  # local runner: one run at a time inside this process
RUNNER = os.environ.get("LPA_RUNNER", "thread")  # thread (local) | cloudrun (a Cloud Run Job execution per run)


@contextmanager
def store() -> Iterator[RunStore]:
    with POOL.connection() as conn:  # borrowed from the pool, returned after the request
        yield RunStore(conn)


class StartRun(BaseModel):
    portal: str
    chaos: str = ""


class Decision(BaseModel):
    decision: str
    note: str = ""
    reviewer: str = "demo-reviewer"


def _execute(run_id: str, portal: str, chaos: str) -> None:
    try:
        with POOL.connection() as conn:
            execute(run_id, portal, chaos, conn)
    finally:
        _lock.release()


def _launch_job(run_id: str, portal: str, chaos: str) -> None:
    """Cloud Run Jobs: start one execution of the agent job with this run's parameters (D21). The API's service
    account may only run this one job (a custom role with run.jobs.runWithOverrides on it, nothing else)."""
    import google.auth
    from google.auth.transport.requests import AuthorizedSession
    creds, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
    job = os.environ["LPA_RUN_JOB"]  # projects/<p>/locations/<region>/jobs/<name>
    env = [{"name": "RUN_ID", "value": run_id}, {"name": "PORTAL", "value": portal}, {"name": "CHAOS", "value": chaos}]
    resp = AuthorizedSession(creds).post(f"https://run.googleapis.com/v2/{job}:run",
                                         json={"overrides": {"containerOverrides": [{"env": env}]}}, timeout=30)
    resp.raise_for_status()


@app.post("/api/runs")
def start_run(body: StartRun):
    if body.portal not in ALLOWED_PORTALS:
        raise HTTPException(400, "only portals a, b and c can be run from the console (d is held out)")
    if body.chaos not in CHAOS_MODES:
        raise HTTPException(400, f"unknown chaos mode {body.chaos!r}")
    with store() as rs:  # limits live in Postgres, so they hold across API instances (D21)
        recent = rs.conn.execute(
            "SELECT count(*) FILTER (WHERE started_at > now() - interval '1 hour') AS last_hour, "
            "count(*) FILTER (WHERE status = 'running' AND started_at > now() - interval '20 minutes') AS running "
            "FROM runs").fetchone()
    if recent["last_hour"] >= RUNS_PER_HOUR:
        raise HTTPException(429, "run limit reached for this hour")
    if recent["running"] or (RUNNER == "thread" and not _lock.acquire(blocking=False)):
        raise HTTPException(409, "a run is already in progress")
    run_id = f"{datetime.now():%Y%m%d-%H%M%S}-{body.portal}"
    with store() as rs:
        rs.start(run_id, body.portal, body.chaos)
    if RUNNER == "cloudrun":
        try:
            _launch_job(run_id, body.portal, body.chaos)
        except Exception as e:
            with store() as rs:
                rs.finish(run_id, "error", f"could not start the job: {e!r}"[:300], 0, 0, 0)
            raise HTTPException(502, "could not start the run") from e
    else:
        threading.Thread(target=_execute, args=(run_id, body.portal, body.chaos), daemon=True).start()
    return {"run_id": run_id}


@app.get("/api/runs")
def list_runs():
    with store() as rs:
        return jsonable(rs.conn.execute("SELECT * FROM runs ORDER BY started_at DESC LIMIT 30").fetchall())


@app.get("/api/runs/{run_id}")
def get_run(run_id: str):
    with store() as rs:
        run_row = rs.conn.execute("SELECT * FROM runs WHERE run_id=%s", (run_id,)).fetchone()
        steps = rs.conn.execute("SELECT idx, n, action, ok, result, screenshot <> '' AS has_shot FROM steps "
                                "WHERE run_id=%s ORDER BY idx", (run_id,)).fetchall()
        items = rs.conn.execute("SELECT * FROM review_items WHERE run_id=%s ORDER BY number", (run_id,)).fetchall()
    if not run_row:
        raise HTTPException(404, "run not found")
    return {"run": jsonable([run_row])[0], "steps": jsonable(steps), "review": jsonable(items)}


def _local(ref: str) -> str:
    """A stored file reference, resolved safely: gs:// objects as they are; local files only under this app's runs
    folder, located by their part after "runs/" (paths written before the repo was renamed or moved still work)."""
    if not ref or ref.startswith("gs://"):
        return ref
    rel = ref.split("/runs/", 1)[1] if "/runs/" in ref else ""
    path = (RUNS_DIR / rel).resolve()
    return str(path) if rel and RUNS_DIR.resolve() in path.parents else ""


@app.get("/api/runs/{run_id}/steps/{idx}.png")
def step_screenshot(run_id: str, idx: int):
    with store() as rs:
        row = rs.conn.execute("SELECT screenshot FROM steps WHERE run_id=%s AND idx=%s", (run_id, idx)).fetchone()
    ref = _local(row["screenshot"] if row else "")
    data = storage.read_bytes(ref) if ref else None
    if data is None:
        raise HTTPException(404, "no screenshot")
    return Response(data, media_type="image/png")


@app.get("/api/review")
def review(status: str | None = None):
    q, args = "SELECT i.*, r.portal FROM review_items i JOIN runs r USING (run_id)", ()
    if status:
        q, args = q + " WHERE i.status=%s", (status,)
    with store() as rs:
        return jsonable(rs.conn.execute(q + " ORDER BY item_id DESC LIMIT 200", args).fetchall())


@app.get("/api/review/{item_id}")
def review_item(item_id: int):
    with store() as rs:
        item = rs.conn.execute("SELECT i.*, r.portal FROM review_items i JOIN runs r USING (run_id) "
                               "WHERE item_id=%s", (item_id,)).fetchone()
        if not item:
            raise HTTPException(404, "item not found")
        po_number = (item["extracted"] or {}).get("po_number")
        orders = PostgresOrderSystem(rs.conn)
        po = orders.get_po(po_number) if po_number else None
        received = orders.received_qty(po_number) if po else {}
    order = None if po is None else {
        "po_number": po.po_number,
        "lines": [{"sku": ln.sku, "description": ln.description, "qty": ln.qty, "unit_price": str(ln.unit_price),
                   "received": received.get(ln.sku, 0)} for ln in po.lines]}
    return {"item": jsonable([item])[0], "order": order}


@app.get("/api/review/{item_id}/page.png")
def review_page(item_id: int):
    with store() as rs:
        row = rs.conn.execute("SELECT pdf FROM review_items WHERE item_id=%s", (item_id,)).fetchone()
    ref = _local(row["pdf"] if row and row["pdf"] else "")
    data = storage.read_bytes(ref) if ref else None
    if data is None:
        raise HTTPException(404, "no document")
    buf = io.BytesIO()
    pdfium.PdfDocument(data)[0].render(scale=1.6).to_pil().save(buf, "PNG", optimize=True)
    return Response(buf.getvalue(), media_type="image/png", headers={"Cache-Control": "max-age=3600"})


@app.post("/api/review/{item_id}")
def decide(item_id: int, body: Decision):
    try:
        with store() as rs:
            row = rs.decide(item_id, body.decision, body.reviewer, body.note)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    if not row:
        raise HTTPException(409, "item not found or already decided")
    return row


app.include_router(process_router)  # see -> predict: the process warehouse (D16-D19)


@app.get("/healthz")
def healthz():
    return {"ok": True}
