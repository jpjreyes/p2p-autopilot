"""Deterministic test data: the client's order system, the suppliers' invoices, and the right answer for each.

Two sides of the same business, kept separate on purpose:
  - order system (the client's): purchase orders and goods receipts. The agent will compare against these.
  - supplier portals (three suppliers'): invoices and credit notes. The agent has to go and get these.

Every invoice gets a ground-truth verdict computed here, before any agent exists:
  match, price_above_po, qty_above_received, duplicate, unknown_po, credit_note.
Money is Decimal end to end and serialized as strings.

Usage:  uv run python -m legacy_portal.data.generate   (writes data/generated/)
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
START, END = date(2026, 8, 3), date(2026, 10, 30)
OUT_DIR = Path(__file__).resolve().parents[3] / "data" / "generated"


def money(x) -> Decimal:
    return Decimal(x).quantize(CENT, rounding=ROUND_HALF_UP)


@dataclass(frozen=True)
class Supplier:
    id: str
    name: str
    portal: str  # "a", "b", "c"
    held_out: bool
    invoice_prefix: str
    catalog: tuple[tuple[str, str, str], ...]  # (sku, description, unit price)


SUPPLIERS = (
    Supplier("SUP-ACME", "Acme Fasteners Inc.", "a", False, "INV-",
             (("HB-M8-40", "Hex bolt M8 x 40, zinc", "0.40"), ("HN-M8", "Hex nut M8, zinc", "0.08"),
              ("FW-M8", "Flat washer M8", "0.05"), ("SS-M6-20", "Socket screw M6 x 20, stainless", "0.62"),
              ("AN-M10", "Anchor bolt M10 x 100", "1.85"), ("TR-M12-1M", "Threaded rod M12, 1 m", "4.20"))),
    Supplier("SUP-VALVEX", "Valvex Industrial GmbH", "b", False, "VX/2026/",
             (("BV-050", "Ball valve DN50, PN16", "48.90"), ("GV-080", "Gate valve DN80, cast iron", "132.00"),
              ("CV-025", "Check valve DN25, brass", "21.75"), ("GK-050", "Flange gasket DN50, EPDM", "2.30"),
              ("PG-100", "Pressure gauge 0-10 bar", "17.40"))),
    Supplier("SUP-SAFEG", "SafeGuard Supply Co.", "c", False, "SG-26-",
             (("HH-W", "Hard hat, white, ANSI Z89.1", "12.50"), ("GL-NIT-L", "Nitrile gloves L, box of 100", "9.80"),
              ("SG-CLR", "Safety glasses, clear", "3.15"), ("HV-VEST-XL", "Hi-vis vest XL, class 2", "7.60"),
              ("EP-200", "Ear plugs, box of 200", "18.90"))),
    # Portal D: the fresh held-out (D10). Nobody runs the agent on it before the final eval.
    Supplier("SUP-KEYST", "Keystone Electrical Supply", "d", True, "KES/26/",
             (("CB-20A", "Circuit breaker 20A, 1-pole", "11.40"), ("WR-12-250", "THHN wire 12 AWG, 250 ft", "42.75"),
              ("JB-4SQ", "Junction box 4in square", "3.85"), ("LT-LED-4", "LED troffer 2x4, 40W", "68.00"),
              ("CN-WN-100", "Wire nuts, bag of 100", "6.20"))),
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


def _rand_date(rng: random.Random, lo: date, hi: date) -> date:
    return lo + timedelta(days=rng.randrange((hi - lo).days + 1))


def generate(seed: int = SEED) -> dict:
    rng = random.Random(seed)
    pos: list[PurchaseOrder] = []
    grs: list[GoodsReceipt] = []
    docs: list[Document] = []
    truths: list[Truth] = []
    po_seq, gr_seq = 5500, 8800

    for sup in SUPPLIERS:
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

        def new_po(order_day: date, sup: Supplier = sup) -> tuple[PurchaseOrder, GoodsReceipt]:
            nonlocal po_seq, gr_seq
            po_seq += rng.randint(1, 7)
            gr_seq += rng.randint(1, 5)
            items = rng.sample(sup.catalog, k=rng.randint(1, 3))
            lines = [Line(sku, desc, rng.choice([10, 20, 25, 50, 100, 200, 500]) if Decimal(p) < 5
                          else rng.randint(2, 24), p) for sku, desc, p in items]
            po = PurchaseOrder(f"PO-{po_seq}", sup.id, order_day.isoformat(), lines)
            gr = GoodsReceipt(f"GR-{gr_seq}", po.po_number, (order_day + timedelta(days=rng.randint(3, 9))).isoformat(),
                              [{"sku": ln.sku, "qty_received": ln.qty} for ln in lines])
            return po, gr

        for i, kind in enumerate(plan):
            doc_id = f"{sup.portal}-{i + 1:02d}"
            issue = _rand_date(rng, START, END)
            due = issue + timedelta(days=30)

            if kind == "duplicate":
                orig = rng.choice(issued)
                issue = date.fromisoformat(orig.issue_date) + timedelta(days=rng.randint(10, 20))
                doc = Document(doc_id, sup.id, sup.portal, "invoice", next_number(), issue.isoformat(),
                               (issue + timedelta(days=30)).isoformat(), orig.po_number, "open",
                               [Line(**asdict(ln)) for ln in orig.lines], notes="Reminder: invoice re-sent")
                truth = Truth(doc_id, sup.portal, sup.id, doc.number, "invoice", True, "duplicate", "0.00",
                              f"Same PO {orig.po_number} and same lines/amount as {orig.number}; pay once only.")
            elif kind == "unknown_po":
                po_seq += 1
                ghost = f"PO-{po_seq + 9000}"  # never created in the order system
                items = rng.sample(sup.catalog, k=1)
                doc = Document(doc_id, sup.id, sup.portal, "invoice", next_number(), issue.isoformat(),
                               due.isoformat(), ghost, "open", [Line(items[0][0], items[0][1], 12, items[0][2])])
                truth = Truth(doc_id, sup.portal, sup.id, doc.number, "invoice", True, "unknown_po", None,
                              f"{ghost} does not exist in the order system; a human must find out who ordered this.")
            elif kind == "credit_note":
                orig = rng.choice(issued)
                issue = date.fromisoformat(orig.issue_date) + timedelta(days=rng.randint(5, 15))
                orig_po_number, base = orig.po_number, orig.lines[0]
                doc = Document(doc_id, sup.id, sup.portal, "credit_note", next_number(), issue.isoformat(),
                               issue.isoformat(), orig_po_number, "open",
                               [Line(base.sku, f"Credit: {base.description} (damaged in transit)", 2, base.unit_price)])
                truth = Truth(doc_id, sup.portal, sup.id, doc.number, "credit_note", True, "credit_note", None,
                              "Credit note, not an invoice: nothing to pay; apply against the supplier balance.")
            else:
                order_day = issue - timedelta(days=rng.randint(10, 25))
                po, gr = new_po(order_day)
                inv_lines = [Line(**asdict(ln)) for ln in po.lines]
                if kind == "price_above_po":
                    j = rng.randrange(len(inv_lines))
                    bump = Decimal(rng.choice(["1.05", "1.08", "1.12", "1.15"]))
                    inv_lines[j].unit_price = str(money(Decimal(po.lines[j].unit_price) * bump))
                    expected = sum((ln.total for ln in po.lines), Decimal(0))
                    why = (f"{inv_lines[j].sku} billed at {inv_lines[j].unit_price} vs PO price "
                           f"{po.lines[j].unit_price}; pay at PO price.")
                elif kind == "qty_above_received":
                    j = rng.randrange(len(po.lines))
                    short = max(1, po.lines[j].qty // rng.choice([5, 10, 4]))
                    gr.lines[j]["qty_received"] = po.lines[j].qty - short
                    expected = sum((money(Decimal(ln.unit_price) * gl["qty_received"])
                                    for ln, gl in zip(po.lines, gr.lines)), Decimal(0))
                    why = (f"{po.lines[j].sku}: billed {po.lines[j].qty}, received {gr.lines[j]['qty_received']} "
                           f"({gr.gr_number}); pay for received quantity.")
                else:
                    expected = sum((ln.total for ln in po.lines), Decimal(0))
                    why = "Invoice matches PO prices and received quantities."
                pos.append(po), grs.append(gr)
                doc = Document(doc_id, sup.id, sup.portal, "invoice", next_number(), issue.isoformat(),
                               due.isoformat(), po.po_number, "open", inv_lines)
                truth = Truth(doc_id, sup.portal, sup.id, doc.number, "invoice", True, kind, str(money(expected)), why)

            truth.fields = {"number": doc.number, "po_number": doc.po_number, "issue_date": doc.issue_date,
                            "total": doc.total, "lines": [asdict(ln) for ln in doc.lines]}
            docs.append(doc), truths.append(truth)
            if kind in ("match", "price_above_po", "qty_above_received"):
                issued.append(doc)

        # Historical paid invoices: shown on the portal, out of scope.
        for k in range(PAID_PER_SUPPLIER):
            doc_id = f"{sup.portal}-p{k + 1}"
            issue = _rand_date(rng, date(2026, 5, 4), date(2026, 7, 24))
            po, gr = new_po(issue - timedelta(days=14))
            pos.append(po), grs.append(gr)
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
