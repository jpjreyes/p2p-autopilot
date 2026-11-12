"""predict -> act (D18c): the block risk of the PO an invoice bills, shown to the reviewer next to the 3-way match.

The portal invoices bill real SAP purchase orders, so the model's invoice-time score for that PO's lines (written by
`predict --worklist` as m_line_block_score) can travel with the review item: "block risk 0.84: a line on this invoice
has no goods receipt yet". It is evidence only. It never changes a verdict or a payable amount (money stays in code).
Returns None when the warehouse or the PO isn't there, so the pipeline works the same without it.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import duckdb

from p2p_autopilot.process.warehouse import DEFAULT_DB


@lru_cache(maxsize=512)
def block_note(po_number: str, db: Path = DEFAULT_DB) -> str | None:
    po = po_number.removeprefix("PO-").strip()
    if not po.isdigit() or not db.exists():
        return None
    try:
        con = duckdb.connect(str(db), read_only=True)
        try:
            row = con.execute("SELECT p_block, reasons FROM m_line_block_score WHERE po = ? "
                              "ORDER BY p_block DESC LIMIT 1", [po]).fetchone()
        finally:
            con.close()
    except duckdb.Error:  # table not built yet, or the file is being rewritten: no note, never a failure
        return None
    if row is None:
        return None
    p, reasons = row
    level = "high" if p >= 0.6 else "medium" if p >= 0.3 else "low"
    if level == "low":  # the features that nudged a small score up aren't reasons anyone should act on
        return f"payment-block risk {p:.2f} (low) when SAP recorded this PO's invoice (model, not a verdict)"
    why = "; ".join(reasons) if reasons else "no single reason stands out"
    return f"payment-block risk {p:.2f} ({level}) when SAP recorded this PO's invoice: {why} (model, not a verdict)"
