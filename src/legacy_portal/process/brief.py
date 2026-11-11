"""The weekly risk brief (D19): the analyst works on a schedule instead of waiting for questions.

Every Monday (Cloud Scheduler in production; `--as-of` here) it runs a fixed set of analyses on the real SAP log for
the week that just ended and writes one page for the AP lead. Code computes every number (SQL, kept next to each
section so anyone can re-run it); the model only writes the summary, and Process Copilot's grounding check rejects the summary if it
states a number no analysis produced (one retry with the offending numbers named, then they're marked unverified).

Sections:
  week          lines ordered, invoices recorded, payments made (and EUR) in the week
  paid_early    payments this week on 3-way lines with no goods receipt before the payment (Process Copilot's EUR 1.75M rule)
  open_long     invoices still unpaid at the end of the week, open longer than 90% of that vendor's paid invoices
  block_risk    open invoices the payment-block model flags (D18), with the model's reasons (latest week only)
  vendors       the vendors with the most money in the two risks above

Run:  uv run python -m legacy_portal.process.brief [--as-of 2019-01-19] [--no-llm]
"""

from __future__ import annotations

import argparse
import json
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

import duckdb

from legacy_portal.process import grounding
from legacy_portal.process.warehouse import DEFAULT_DB, ROOT

BRIEFS = ROOT / "runs" / "briefs"

SECTIONS: dict[str, tuple[str, str]] = {
    "week": ("This week in purchase-to-pay", """
        SELECT count(*) FILTER (WHERE activity = 'Create Purchase Order Item')                  AS lines_ordered,
               count(*) FILTER (WHERE activity = 'Record Invoice Receipt')                      AS invoices_recorded,
               count(*) FILTER (WHERE activity = 'Clear Invoice')                               AS payments,
               round(sum(c.value_eur) FILTER (WHERE activity = 'Clear Invoice'))                AS eur_paid
        FROM events e JOIN cases c USING (case_id)
        WHERE e.is_canonical AND e.ts >= $start AND e.ts < $end"""),
    "paid_early": ("Paid before any goods receipt (3-way match)", """
        WITH pay AS (
            SELECT e.case_id, min(e.ts) AS paid FROM events e
            WHERE e.is_canonical AND e.activity = 'Clear Invoice' AND e.ts >= $start AND e.ts < $end GROUP BY 1)
        SELECT count(*) AS lines, round(sum(c.value_eur)) AS eur, count(DISTINCT c.vendor) AS vendors
        FROM pay p JOIN cases c USING (case_id)
        WHERE c.item_category LIKE '3-way%' AND NOT EXISTS (
            SELECT 1 FROM events g WHERE g.case_id = p.case_id AND g.is_canonical
              AND g.activity = 'Record Goods Receipt' AND g.ts < p.paid)"""),
    "open_long": ("Open longer than the vendor usually takes", """
        WITH f AS (
            SELECT case_id,
                   bool_or(activity = 'Record Goods Receipt')                            AS gr,
                   min(ts) FILTER (WHERE activity = 'Record Invoice Receipt')            AS inv,
                   min(ts) FILTER (WHERE activity = 'Clear Invoice')                     AS paid,
                   bool_or(activity = 'Delete Purchase Order Item')                      AS deleted
            FROM events WHERE is_canonical AND ts_status IN ('ok', 'repaired') AND ts < $end GROUP BY 1),
        vendor_pay AS (  -- each vendor's p90 of invoice-to-payment days on invoices paid before the week ended
            SELECT c.vendor, count(*) AS n_paid,
                   quantile_cont(date_diff('second', f.inv, f.paid) / 86400.0, 0.9) AS p90_days
            FROM f JOIN cases c USING (case_id) WHERE f.paid >= f.inv GROUP BY 1)
        SELECT count(*) AS lines, round(sum(c.value_eur)) AS eur,
               round(median(date_diff('day', CAST(f.inv AS DATE), CAST($end AS DATE) - 1))) AS median_days_open
        FROM f JOIN cases c USING (case_id) JOIN vendor_pay v ON v.vendor = c.vendor
        WHERE f.gr AND f.inv IS NOT NULL AND f.paid IS NULL AND NOT f.deleted AND v.n_paid >= 30
          AND date_diff('day', CAST(f.inv AS DATE), CAST($end AS DATE) - 1) > v.p90_days"""),
    "block_risk": ("Invoices likely to be blocked (model, D18)", """
        SELECT count(*) FILTER (WHERE flagged) AS flagged, round(sum(value_eur) FILTER (WHERE flagged)) AS eur,
               count(*) AS open_scored
        FROM m_block_risk"""),
    "block_top": ("Largest flagged invoices", """
        SELECT case_id, vendor, round(value_eur) AS eur, p_block, reasons
        FROM m_block_risk WHERE flagged ORDER BY value_eur DESC LIMIT 5"""),
}

SYSTEM = """You write the weekly purchase-to-pay risk brief for the head of accounts payable at a coatings manufacturer.
Use ONLY the numbers in the analyses given; never compute new ones except simple differences. Plain English, short
bullets, most money at risk first, one concrete next action per risk. No greetings. Each bullet ends with the section
key in square brackets, e.g. [paid_early], so the reader can open the query behind it."""

SCHEMA = {"type": "object", "properties": {
    "headline": {"type": "string"},
    "bullets": {"type": "array", "items": {"type": "string"}}},
    "required": ["headline", "bullets"]}


def run_sections(con: duckdb.DuckDBPyConnection, start: date, end: date, latest: bool) -> dict[str, dict]:
    out = {}
    for key, (title, sql) in SECTIONS.items():
        if key.startswith("block") and not latest:  # the model's worklist is as of the end of the data only
            continue
        cur = con.execute(sql, {k: v for k, v in (("start", start), ("end", end)) if f"${k}" in sql})
        cols = [d[0] for d in cur.description]
        rows = [[float(v) if isinstance(v, Decimal) else v for v in r] for r in cur.fetchall()]
        out[key] = {"title": title, "sql": " ".join(sql.split()), "columns": cols, "rows": rows}
    return out


def write_summary(sections: dict, backend, as_of: date) -> tuple[dict, list[str]]:
    facts = {k: {"title": v["title"], "columns": v["columns"], "rows": v["rows"]} for k, v in sections.items()}
    prompt = f"Week ending {as_of - timedelta(days=1)}. Analyses:\n{json.dumps(facts, default=str)}"
    results = {k: v["rows"] for k, v in sections.items()}
    bad: list[str] = []
    for _ in range(2):
        res = backend.complete(SYSTEM, prompt + (f"\n\nThese numbers are not in the analyses, remove them: {bad}"
                                                 if bad else ""), SCHEMA)
        text = res.data.get("headline", "") + "\n" + "\n".join(res.data.get("bullets", []))
        bad = [n.text for n in grounding.check(text, results) if n.status == "ungrounded"]
        if not bad:
            break
    return res.data, bad


def brief(as_of: date | None = None, use_llm: bool = True, db: Path = DEFAULT_DB, out_dir: Path = BRIEFS) -> dict:
    from legacy_portal import tracing
    with tracing.span("weekly_brief", "CHAIN", **{"lpa.as_of": str(as_of) if as_of else "latest"}) as s:
        out = _brief(as_of, use_llm, db, out_dir)
        s.set_attribute("lpa.sections", len(out["sections"]))
        s.set_attribute("lpa.unverified_numbers", len(out.get("unverified_numbers", [])))
        return out


def _brief(as_of: date | None, use_llm: bool, db: Path, out_dir: Path) -> dict:
    con = duckdb.connect(str(db), read_only=True)
    data_end = con.execute("SELECT data_end FROM m_data_end").fetchone()[0]
    as_of = as_of or data_end + timedelta(days=1)  # the brief for the week that ends with the data
    start = as_of - timedelta(days=7)
    sections = run_sections(con, start, as_of, latest=as_of > data_end)
    out = {"week": [str(start), str(as_of - timedelta(days=1))], "sections": sections}
    if use_llm:
        from legacy_portal.llm import get_backend
        summary, unverified = write_summary(sections, get_backend(), as_of)
        out.update(summary=summary, unverified_numbers=unverified)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"brief-{as_of}.json"
    path.write_text(json.dumps(out, indent=1, default=str))
    out["path"] = str(path)
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--as-of", type=date.fromisoformat, help="first day after the week (default: day after data end)")
    ap.add_argument("--no-llm", action="store_true", help="numbers only, no written summary")
    a = ap.parse_args()
    b = brief(a.as_of, not a.no_llm)
    print(f"brief for {b['week'][0]} .. {b['week'][1]} -> {b['path']}")
    for k, s in b["sections"].items():
        print(f"  {k:12} {dict(zip(s['columns'], s['rows'][0])) if len(s['rows']) == 1 else f'{len(s['rows'])} rows'}")
    if "summary" in b:
        print("\n" + b["summary"]["headline"])
        for line in b["summary"]["bullets"]:
            print(" -", line)
        print("unverified numbers:", b["unverified_numbers"] or "none")


if __name__ == "__main__":
    main()
