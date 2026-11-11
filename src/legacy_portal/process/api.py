"""Read-only API over the process warehouse (see -> predict): the console's process pages read these.

  GET /api/process/overview          headline numbers, compliance by match type, biggest waits, data window
  GET /api/process/risk?limit=50     open invoices the payment-block model flags, with reasons + the model card
  GET /api/process/risk/{case_id}    predict_risk(case): one PO line's block probability and reasons
  GET /api/process/brief             the latest weekly brief
"""

from __future__ import annotations

import json
from pathlib import Path

import duckdb
from fastapi import APIRouter, HTTPException

from legacy_portal.process.brief import BRIEFS
from legacy_portal.process.predict import MODELS
from legacy_portal.process.warehouse import DEFAULT_DB

router = APIRouter(prefix="/api/process")


def _rows(sql: str, params: list | None = None, db: Path = DEFAULT_DB) -> list[dict]:
    if not db.exists():
        raise HTTPException(503, "process warehouse not built (python -m legacy_portal.process.warehouse)")
    con = duckdb.connect(str(db), read_only=True)
    try:
        cur = con.execute(sql, params or [])
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, r)) for r in cur.fetchall()]
    finally:
        con.close()


@router.get("/overview")
def overview():
    return {
        "data_end": str(_rows("SELECT data_end FROM m_data_end")[0]["data_end"]),
        "totals": _rows("SELECT count(*) AS lines, round(sum(value_eur)) AS eur, count(DISTINCT vendor) AS vendors, "
                        "min(start_ts)::DATE::VARCHAR AS first_day FROM cases")[0],
        "summary": _rows("SELECT metric, value, eur, note FROM m_summary"),
        "by_match_type": _rows("""
            SELECT c.item_category AS match_type, count(*) AS lines, round(sum(c.value_eur)) AS eur,
                   coalesce(max(k.violations), 0) AS paid_before_gr, coalesce(max(k.eur), 0) AS eur_paid_before_gr
            FROM cases c LEFT JOIN m_conformance k ON k.item_category = c.item_category
                 AND k.rule = 'paid before any goods receipt'
            GROUP BY 1 ORDER BY lines DESC"""),
        "bottlenecks": _rows("SELECT from_activity, to_activity, n_waits, median_days, p90_days, pct_of_all_waiting "
                             "FROM m_bottlenecks ORDER BY total_wait_days DESC LIMIT 6"),
    }


@router.get("/risk")
def risk(limit: int = 50):
    card_path = MODELS / "block-invoice-card.json"
    return {
        "summary": _rows("SELECT count(*) AS open_scored, count(*) FILTER (WHERE flagged) AS flagged, "
                         "round(sum(value_eur) FILTER (WHERE flagged)) AS eur_flagged FROM m_block_risk")[0],
        "items": _rows("SELECT case_id, vendor, round(value_eur, 2) AS eur, invoice_recorded::VARCHAR AS "
                       "invoice_recorded, p_block, reasons FROM m_block_risk WHERE flagged "
                       "ORDER BY value_eur DESC LIMIT ?", [min(max(limit, 1), 500)]),
        "model": json.loads(card_path.read_text()) if card_path.exists() else None,
    }


@router.get("/risk/{case_id}")
def predict_risk(case_id: str):
    """The agent's tool: block probability and reasons for one open PO line (from the D18 worklist)."""
    rows = _rows("SELECT case_id, vendor, value_eur, invoice_recorded::VARCHAR AS invoice_recorded, p_block, flagged, "
                 "reasons FROM m_block_risk WHERE case_id = ?", [case_id])
    if not rows:
        raise HTTPException(404, "not an open invoice in the scored worklist")
    return rows[0]


@router.get("/brief")
def latest_brief():
    from legacy_portal import storage
    text = storage.latest_text("briefs/", BRIEFS)
    if not text:
        raise HTTPException(404, "no brief yet (python -m legacy_portal.process.brief)")
    return json.loads(text)
