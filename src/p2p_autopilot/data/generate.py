"""Deterministic test data: the client's order system, the suppliers' invoices, and the right answer for each.

Since the merge with Process Copilot (D17), every supplier is the face of one real SAP vendor from the BPI 2019 log, and its
invoices are built from that vendor's real purchase orders (PO numbers, line items, line amounts in EUR, order, goods
receipt and invoice dates: `data/bpi/portal_sample.json`, from p2p_autopilot.process.portal_sample). Synthetic on top:
supplier names and portals, invoice numbers, the quantity x unit-price split of each line amount, and the planted
problems the real data doesn't contain (price above PO, duplicates, unknown POs, credit notes). "Billed for more than
received" is real wherever the vendor invoiced before the goods arrived.

Two sides of the same business, kept separate on purpose:
  - order system (the client's): purchase orders and goods receipts. The agent will compare against these.
  - supplier portals (three suppliers'): invoices and credit notes. The agent has to go and get these.

Every invoice gets a ground-truth verdict computed here, before any agent exists:
  match, price_above_po, qty_above_received, duplicate, unknown_po, credit_note.
Money is Decimal end to end and serialized as strings.

Usage:  uv run python -m p2p_autopilot.data.generate   (writes data/generated/)
"""

from __future__ import annotations

import json
import random
from dataclasses import asdict, dataclass, field
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

CENT = Decimal("0.01")
SEED = 20261108
OUT_DIR = Path(__file__).resolve().parents[3] / "data" / "generated"
SAMPLE = Path(__file__).resolve().parents[3] / "data" / "bpi" / "portal_sample.json"


def money(x) -> Decimal:
    return Decimal(x).quantize(CENT, rounding=ROUND_HALF_UP)


@dataclass(frozen=True)
class Supplier:
    id: str
    name: str
    portal: str  # "a", "b", "c"
    held_out: bool
    invoice_prefix: str
    vendor: str  # the real SAP vendor (BPI 2019) whose purchase orders this supplier bills


SUPPLIERS = (
    Supplier("SUP-ACME", "Acme Fasteners Inc.", "a", False, "INV-", "vendorID_0660"),
    Supplier("SUP-VALVEX", "Valvex Industrial GmbH", "b", False, "VX/2026/", "vendorID_0011"),
    Supplier("SUP-SAFEG", "SafeGuard Supply Co.", "c", False, "SG-26-", "vendorID_0122"),
    # Portal D: the held-out portal of the final eval (D23-D25); runnable like the others since then.
    Supplier("SUP-KEYST", "Keystone Electrical Supply", "d", False, "KES/26/", "vendorID_0666"),
)

# Planted issues per supplier (the rest are clean matches). Order matters for reproducibility.
PLAN = ["price_above_po", "price_above_po", "qty_above_received", "qty_above_received",
        "duplicate", "unknown_po", "credit_note"]
INVOICES_PER_SUPPLIER = 20  # in scope (open documents)
PAID_PER_SUPPLIER = 3       # historical, already paid: out of scope, the agent should skip them


@dataclass
class Line:
    sku: str
    description: str
    qty: int
    unit_price: str  # Decimal as string

    @property
    def total(self) -> Decimal:
        return money(Decimal(self.unit_price) * self.qty)


@dataclass
class PurchaseOrder:
    po_number: str
    supplier_id: str
    order_date: str
    lines: list[Line]


@dataclass
class GoodsReceipt:
    gr_number: str
    po_number: str
    received_date: str
    lines: list[dict]  # {"sku", "qty_received"}


@dataclass
class Document:
    """An invoice or credit note as the supplier publishes it."""
    doc_id: str           # stable internal id, e.g. "a-07"
    supplier_id: str
    portal: str
    doc_type: str         # "invoice" | "credit_note"
    number: str
    issue_date: str
    due_date: str
    po_number: str
    status: str           # "open" | "paid"
    lines: list[Line]
    total: str = ""
    notes: str = ""

    def __post_init__(self):
        if not self.total:
            sign = -1 if self.doc_type == "credit_note" else 1
            self.total = str(money(sum((ln.total for ln in self.lines), Decimal(0)) * sign))


@dataclass
class Truth:
    doc_id: str
    portal: str
    supplier_id: str
    number: str
    doc_type: str
    in_scope: bool
    verdict: str
    expected_payable: str | None  # what AP should pay; None = needs a human decision
    explanation: str
    fields: dict = field(default_factory=dict)


def _load_sample() -> dict:
    return json.loads(SAMPLE.read_text())


def _split(rng: random.Random, value: str) -> tuple[int, str]:
    """The log records a line's amount, not quantity x unit price: split it (D17). Unit price >= 1.00."""
    v = Decimal(value)
    qty = rng.choice([q for q in (1, 2, 4, 5, 10, 20, 25, 50, 100) if v / q >= 1] or [1])
    return qty, str(money(v / qty))


def generate(seed: int = SEED) -> dict:
    """Invoices built from real SAP purchase orders (D17). Per supplier: 20 open documents (13 clean, 7 issues as in
    PLAN) + 3 already paid. AP processes each invoice on the day it was recorded in SAP, so the order system holds a
    goods receipt only for lines received BEFORE that day."""
    rng = random.Random(seed)
    sample = _load_sample()["vendors"]
    pos: list[PurchaseOrder] = []
    grs: list[GoodsReceipt] = []
    docs: list[Document] = []
    truths: list[Truth] = []

    for sup in SUPPLIERS:
        real = sample[sup.portal]
        goods_first = list(real["goods_first"])
        invoice_first = list(real["invoice_first"])
        rng.shuffle(goods_first)
        rng.shuffle(invoice_first)
        # the 3 historical paid invoices are real POs SAP shows as paid: reserved before the open ones are drawn
        paid_pool = [r for r in goods_first if all(ln["paid"] for ln in r["lines"])][:PAID_PER_SUPPLIER]
        goods_first = [r for r in goods_first if r not in paid_pool]
        plan = PLAN + ["match"] * (INVOICES_PER_SUPPLIER - len(PLAN))
        rng.shuffle(plan)
        # Duplicates and credit notes refer back to an earlier normal invoice, so a plain match goes first.
        first_match = plan.index("match")
        plan[0], plan[first_match] = plan[first_match], plan[0]
        issued: list[Document] = []  # normal invoices (match / price / qty) that later documents can refer to
        inv_seq = {"a": 1040, "b": 310, "c": 40210, "d": 7700}[sup.portal]

        def next_number(sup: Supplier = sup) -> str:
            nonlocal inv_seq
            inv_seq += rng.randint(1, 4)
            return f"{sup.invoice_prefix}{inv_seq:04d}" if sup.portal in "ab" else f"{sup.invoice_prefix}{inv_seq:05d}"

        def real_po(rec: dict, short: bool = False, sup: Supplier = sup) -> tuple[PurchaseOrder, GoodsReceipt | None]:
            """PO and goods receipt as SAP had them on the invoice day. `short`: plant a short delivery on one
            received line (for a vendor that never invoices before delivery)."""
            lines = []
            for ln in rec["lines"]:
                qty, unit = _split(rng, str(ln["value_eur"]))
                lines.append(Line(f"ITEM-{ln['item']}", f"{ln['spend_area']}, PO item {ln['item']}", qty, unit))
            po = PurchaseOrder(f"PO-{rec['po']}", sup.id, rec["lines"][0]["ordered"], lines)
            got = [ln.qty if src["received_before_invoice"] else 0 for ln, src in zip(lines, rec["lines"])]
            if short:
                j = rng.randrange(len(lines))
                got[j] = lines[j].qty - max(1, lines[j].qty // rng.choice([5, 10, 4])) if lines[j].qty > 1 else 0
            if not any(got):
                return po, None
            day = max(src["goods_received"] for src, g in zip(rec["lines"], got) if g and src["goods_received"])
            gr = GoodsReceipt(f"GR-{rec['po'][-7:]}", po.po_number, day,
                              [{"sku": ln.sku, "qty_received": g} for ln, g in zip(lines, got) if g])
            return po, gr

        for i, kind in enumerate(plan):
            doc_id = f"{sup.portal}-{i + 1:02d}"

            if kind == "duplicate":
                orig = rng.choice(issued)
                issue = date.fromisoformat(orig.issue_date) + timedelta(days=rng.randint(10, 20))
                doc = Document(doc_id, sup.id, sup.portal, "invoice", next_number(), issue.isoformat(),
                               (issue + timedelta(days=30)).isoformat(), orig.po_number, "open",
                               [Line(**asdict(ln)) for ln in orig.lines], notes="Reminder: invoice re-sent")
                truth = Truth(doc_id, sup.portal, sup.id, doc.number, "invoice", True, "duplicate", "0.00",
                              f"Same PO {orig.po_number} and same lines/amount as {orig.number}; pay once only.")
            elif kind == "unknown_po":
                ghost = f"PO-49{rng.randrange(10**8):08d}"  # SAP POs here start 45...: this one was never created
                src = rng.choice(goods_first)["lines"][0]
                qty, unit = _split(rng, str(src["value_eur"]))
                issue = date.fromisoformat(src["invoiced"]) + timedelta(days=rng.randint(1, 20))
                doc = Document(doc_id, sup.id, sup.portal, "invoice", next_number(), issue.isoformat(),
                               (issue + timedelta(days=30)).isoformat(), ghost, "open",
                               [Line("ITEM-00010", f"{src['spend_area']}, PO item 00010", qty, unit)])
                truth = Truth(doc_id, sup.portal, sup.id, doc.number, "invoice", True, "unknown_po", None,
                              f"{ghost} does not exist in the order system; a human must find out who ordered this.")
            elif kind == "credit_note":
                orig = rng.choice(issued)
                issue = date.fromisoformat(orig.issue_date) + timedelta(days=rng.randint(5, 15))
                base = orig.lines[0]
                doc = Document(doc_id, sup.id, sup.portal, "credit_note", next_number(), issue.isoformat(),
                               issue.isoformat(), orig.po_number, "open",
                               [Line(base.sku, f"Credit: {base.description} (damaged in transit)", 1, base.unit_price)])
                truth = Truth(doc_id, sup.portal, sup.id, doc.number, "credit_note", True, "credit_note", None,
                              "Credit note, not an invoice: nothing to pay; apply against the supplier balance.")
            else:
                real_short = kind == "qty_above_received" and invoice_first
                rec = invoice_first.pop() if real_short else goods_first.pop()
                po, gr = real_po(rec, short=kind == "qty_above_received" and not real_short)
                issue = date.fromisoformat(rec["lines"][0]["invoiced"])
                inv_lines = [Line(**asdict(ln)) for ln in po.lines]
                received = {g["sku"]: g["qty_received"] for g in (gr.lines if gr else [])}
                if kind == "price_above_po":
                    j = rng.randrange(len(inv_lines))
                    bump = Decimal(rng.choice(["1.05", "1.08", "1.12", "1.15"]))
                    inv_lines[j].unit_price = str(money(Decimal(po.lines[j].unit_price) * bump))
                    expected = sum((ln.total for ln in po.lines), Decimal(0))
                    why = (f"{inv_lines[j].sku} billed at {inv_lines[j].unit_price} vs PO price "
                           f"{po.lines[j].unit_price}; pay at PO price.")
                elif kind == "qty_above_received":
                    expected = sum((money(Decimal(ln.unit_price) * received.get(ln.sku, 0)) for ln in po.lines),
                                   Decimal(0))
                    short = [f"{ln.sku} billed {ln.qty}, received {received.get(ln.sku, 0)}" for ln in po.lines
                             if received.get(ln.sku, 0) < ln.qty]
                    why = ("; ".join(short) + ("; invoiced before the goods arrived (real SAP sequence)"
                                               if real_short else "") + "; pay for received quantity.")
                else:
                    expected = sum((ln.total for ln in po.lines), Decimal(0))
                    why = "Invoice matches PO prices and received quantities."
                pos.append(po)
                if gr:
                    grs.append(gr)
                doc = Document(doc_id, sup.id, sup.portal, "invoice", next_number(), issue.isoformat(),
                               (issue + timedelta(days=30)).isoformat(), po.po_number, "open", inv_lines)
                truth = Truth(doc_id, sup.portal, sup.id, doc.number, "invoice", True, kind, str(money(expected)), why)

            truth.fields = {"number": doc.number, "po_number": doc.po_number, "issue_date": doc.issue_date,
                            "total": doc.total, "lines": [asdict(ln) for ln in doc.lines]}
            docs.append(doc), truths.append(truth)
            if kind in ("match", "price_above_po", "qty_above_received"):
                issued.append(doc)

        # Historical paid invoices: shown on the portal, out of scope. Real POs that SAP shows as paid.
        for k, rec in enumerate(paid_pool):
            doc_id = f"{sup.portal}-p{k + 1}"
            po, gr = real_po(rec)
            pos.append(po)
            if gr:
                grs.append(gr)
            issue = date.fromisoformat(rec["lines"][0]["invoiced"])
            doc = Document(doc_id, sup.id, sup.portal, "invoice", next_number(), issue.isoformat(),
                           (issue + timedelta(days=30)).isoformat(), po.po_number, "paid",
                           [Line(**asdict(ln)) for ln in po.lines])
            docs.append(doc)
            truths.append(Truth(doc_id, sup.portal, sup.id, doc.number, "invoice", False, "already_paid", "0.00",
                                "Already paid; out of scope.", {"number": doc.number}))

    return {
        "suppliers": [asdict(s) for s in SUPPLIERS],
        "order_system": {"purchase_orders": [asdict(p) for p in pos], "goods_receipts": [asdict(g) for g in grs]},
        "documents": [asdict(d) for d in docs],
        "ground_truth": [asdict(t) for t in truths],
    }


def write(out_dir: Path = OUT_DIR, seed: int = SEED) -> dict:
    data = generate(seed)
    out_dir.mkdir(parents=True, exist_ok=True)
    for key in ("order_system", "documents", "ground_truth", "suppliers"):
        (out_dir / f"{key}.json").write_text(json.dumps(data[key], indent=2) + "\n")
    return data


if __name__ == "__main__":
    d = write()
    gt = d["ground_truth"]
    by = {}
    for t in gt:
        by.setdefault((t["portal"], t["verdict"]), 0)
        by[(t["portal"], t["verdict"])] += 1
    print(f"wrote {OUT_DIR}: {len(d['documents'])} documents, "
          f"{len(d['order_system']['purchase_orders'])} POs, {len(d['order_system']['goods_receipts'])} GRs")
    for k in sorted(by):
        print(f"  portal {k[0]}  {k[1]:<20} {by[k]}")
