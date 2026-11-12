"""The real purchase orders behind the supplier portals (D17): a small, committed sample of the BPI 2019 log.

Each mock portal is the face of one real SAP vendor. Its invoices are built from that vendor's real purchase orders:
PO numbers, line items, line amounts (EUR, as ordered), order dates, goods-receipt dates and invoice dates all come from
the log. The log has no quantities, unit prices or item descriptions, so the generator splits each real line amount
into quantity x unit price and labels lines by their spend area.

Picked per vendor: POs with 1-3 lines, 3-way match, an invoice recorded, every line > 0 EUR. Kept in two groups:
  goods_first     every line's goods receipt was recorded before the invoice (normal, should match)
  invoice_first   at least one line was invoiced before its goods arrived (the AP risk behind Process Copilot's EUR 1.75M)

Run (after the warehouse):  uv run python -m p2p_autopilot.process.portal_sample   -> data/bpi/portal_sample.json
"""

from __future__ import annotations

import json
from pathlib import Path

import duckdb

from p2p_autopilot.process.warehouse import DEFAULT_DB, ROOT

OUT = ROOT / "data" / "bpi" / "portal_sample.json"
# portal -> real vendor, chosen so the vendor's spend area fits the portal's trade (process.warehouse spend areas)
VENDORS = {
    "a": ("vendorID_0660", "MRO (components)"),
    "b": ("vendorID_0011", "MRO (components)"),  # 0282 (process automation) has no payments in the log
    "c": ("vendorID_0122", "Laboratory Supplies & Services"),
    "d": ("vendorID_0666", "MRO (components)"),  # held-out portal D
}
PER_GROUP = 40


def sample(db: Path = DEFAULT_DB) -> dict:
    con = duckdb.connect(str(db), read_only=True)
    con.execute("""
        CREATE TEMP TABLE line AS
        WITH f AS (
            SELECT case_id,
                   min(ts) FILTER (WHERE activity = 'Create Purchase Order Item') AS po_ts,
                   min(ts) FILTER (WHERE activity = 'Record Goods Receipt')       AS gr_ts,
                   min(ts) FILTER (WHERE activity = 'Record Invoice Receipt')     AS ir_ts,
                   min(ts) FILTER (WHERE activity = 'Clear Invoice')              AS paid_ts
            FROM events WHERE is_canonical AND ts_status IN ('ok', 'repaired') GROUP BY 1)
        SELECT c.po, c.item, c.vendor, c.item_category, c.sub_spend_area, c.value_eur, f.*
        FROM cases c JOIN f USING (case_id)
        WHERE c.item_category LIKE '3-way%' AND c.value_eur > 0 AND f.ir_ts IS NOT NULL AND f.po_ts IS NOT NULL
    """)
    out: dict = {"source": "BPI Challenge 2019 (4TU, CC BY 4.0), via p2p_autopilot.process.warehouse", "vendors": {}}
    for portal, (vendor, area) in VENDORS.items():
        rows = con.execute("""
            WITH po AS (
                SELECT po, count(*) AS n_items,
                       bool_and(gr_ts IS NOT NULL AND gr_ts < ir_ts) AS goods_first,
                       bool_or(gr_ts IS NULL OR ir_ts < gr_ts)       AS invoice_first,
                       min(ir_ts) AS first_invoice
                FROM line WHERE vendor = ? GROUP BY 1 HAVING count(*) BETWEEN 1 AND 3)
            SELECT p.po, p.goods_first, p.invoice_first, l.item, l.item_category, l.sub_spend_area,
                   l.value_eur, l.po_ts, l.gr_ts, l.ir_ts, l.paid_ts
            FROM po p JOIN line l ON l.po = p.po AND l.vendor = ?
            ORDER BY p.first_invoice, p.po, l.item
        """, [vendor, vendor]).fetchall()
        pos: dict[str, dict] = {}
        for po, gf, inf, item, cat, ssa, value, po_ts, gr_ts, ir_ts, paid_ts in rows:
            rec = pos.setdefault(po, {"po": po, "group": "goods_first" if gf else "invoice_first", "lines": []})
            rec["lines"].append({
                "item": item, "category": cat, "spend_area": ssa or area, "value_eur": round(float(value), 2),
                "ordered": po_ts.date().isoformat(), "goods_received": gr_ts.date().isoformat() if gr_ts else None,
                "invoiced": ir_ts.date().isoformat(), "paid": paid_ts.date().isoformat() if paid_ts else None,
                "received_before_invoice": bool(gr_ts and gr_ts < ir_ts)})
        groups = {g: [p for p in pos.values() if p["group"] == g] for g in ("goods_first", "invoice_first")}
        recent = groups["goods_first"][-PER_GROUP:]  # the most recent ones, plus a few fully paid (paid history)
        paid = [p for p in groups["goods_first"] if p not in recent and all(ln["paid"] for ln in p["lines"])][-5:]
        out["vendors"][portal] = {"vendor": vendor, "spend_area": area,
                                  "goods_first": paid + recent,
                                  "invoice_first": groups["invoice_first"][-PER_GROUP:]}
    return out


def main() -> None:
    data = sample()
    OUT.write_text(json.dumps(data, indent=1) + "\n")
    for portal, v in data["vendors"].items():
        print(f"  portal {portal}: {v['vendor']} ({v['spend_area']}): {len(v['goods_first'])} goods-first POs, "
              f"{len(v['invoice_first'])} invoice-first POs")
    print(f"-> {OUT}")


if __name__ == "__main__":
    main()
