"""3-way match: invoice vs. purchase order vs. goods receipt. Plain code, never the LLM (C1: money is deterministic).

Input is an extracted document (whatever the agent read from the PDF). Output is a verdict with evidence and the
amount AP should pay. Nothing here approves or pays anything: it produces a review item for a human.

Rules, in order:
  already_paid        the AP ledger says this invoice number was already paid: pay nothing (no double payment,
                      whatever the agent downloaded)
  credit_note         a credit memo is not an invoice: nothing to pay, a human applies it to the balance
  unknown_po          the PO doesn't exist in the order system: a human must find out who ordered it
  duplicate           same supplier, same PO, same lines and total as an invoice already processed
  price_above_po      a line billed above the PO's unit price
  qty_above_received  a line billed for more units than the warehouse received
  match               everything ties out

Payable amount for invoices against a known PO, line by line:
  min(billed qty, received qty) x min(billed price, PO price)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal

from legacy_portal.orders.store import OrderSystem

CENT = Decimal("0.01")


@dataclass(frozen=True)
class DocLine:
    sku: str
    qty: int
    unit_price: Decimal


@dataclass(frozen=True)
class ExtractedDoc:
    supplier_id: str
    number: str
    doc_type: str  # "invoice" | "credit_note"
    po_number: str
    issue_date: str  # ISO
    total: Decimal
    lines: tuple[DocLine, ...]

    def fingerprint(self) -> tuple:
        """What makes two invoices 'the same bill' regardless of the invoice number."""
        return (self.supplier_id, self.po_number, self.total,
                tuple(sorted((ln.sku, ln.qty, ln.unit_price) for ln in self.lines)))


@dataclass
class Verdict:
    number: str
    verdict: str
    payable: Decimal | None  # None = a human must decide
    evidence: list[str] = field(default_factory=list)
    issues: list[str] = field(default_factory=list)  # all problems found; `verdict` is the first by priority


class Ledger:
    """Invoices already processed, for duplicate detection. In-memory now; a table once runs are persisted."""

    def __init__(self):
        self._seen: dict[tuple, str] = {}

    def seen(self, doc: ExtractedDoc) -> str | None:
        return self._seen.get(doc.fingerprint())

    def add(self, doc: ExtractedDoc) -> None:
        self._seen.setdefault(doc.fingerprint(), doc.number)


def _q(x: Decimal) -> Decimal:
    return x.quantize(CENT, rounding=ROUND_HALF_UP)


def match(doc: ExtractedDoc, orders: OrderSystem, ledger: Ledger) -> Verdict:
    if orders.is_paid(doc.supplier_id, doc.number):
        return Verdict(doc.number, "already_paid", Decimal("0.00"),
                       [f"{doc.number} is already in the AP ledger as paid; nothing to pay."])
    if doc.doc_type == "credit_note":
        return Verdict(doc.number, "credit_note", None,
                       [f"Credit memo for {doc.total} against {doc.po_number}; apply to the supplier balance."])

    po = orders.get_po(doc.po_number)
    if po is None:
        return Verdict(doc.number, "unknown_po", None, [f"{doc.po_number} not found in the order system."])

    original = ledger.seen(doc)
    if original and original != doc.number:
        return Verdict(doc.number, "duplicate", Decimal("0.00"),
                       [f"Same supplier, PO {doc.po_number}, lines and total {doc.total} as {original}."])
    ledger.add(doc)

    po_lines = {ln.sku: ln for ln in po.lines}
    received = orders.received_qty(doc.po_number)
    issues, evidence, payable = [], [], Decimal(0)
    for ln in doc.lines:
        pol = po_lines.get(ln.sku)
        if pol is None:
            issues.append("line_not_on_po")
            evidence.append(f"{ln.sku} is billed but not on {doc.po_number}.")
            continue
        got = received.get(ln.sku, 0)
        if ln.unit_price > pol.unit_price:
            issues.append("price_above_po")
            evidence.append(f"{ln.sku}: billed {ln.unit_price} vs PO price {pol.unit_price}.")
        if ln.qty > got:
            issues.append("qty_above_received")
            evidence.append(f"{ln.sku}: billed {ln.qty}, received {got}.")
        payable += min(ln.qty, got) * min(ln.unit_price, pol.unit_price)

    line_sum = _q(sum((ln.unit_price * ln.qty for ln in doc.lines), Decimal(0)))
    if line_sum != _q(doc.total):
        issues.append("total_mismatch")
        evidence.append(f"Lines add up to {line_sum} but the invoice total says {doc.total}.")

    priority = ["line_not_on_po", "total_mismatch", "price_above_po", "qty_above_received"]
    issues = sorted(set(issues), key=priority.index)
    if not issues:
        return Verdict(doc.number, "match", _q(payable), ["Prices and quantities tie out to PO and receipt."])
    needs_human = issues[0] in ("line_not_on_po", "total_mismatch")
    return Verdict(doc.number, issues[0], None if needs_human else _q(payable), evidence, issues)
