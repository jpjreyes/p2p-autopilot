"""The matcher against the ground truth, given perfect extraction. Any miss here is a matcher bug, not an agent bug.

Runs against an in-memory order system built from the same generated data, so it needs no database.
"""

from decimal import Decimal

import pytest

from legacy_portal.data.generate import generate
from legacy_portal.matching import DocLine, ExtractedDoc, Ledger, match
from legacy_portal.orders.store import POLine, PurchaseOrder

DATA = generate()


class MemoryOrderSystem:
    def __init__(self, data):
        os_ = data["order_system"]
        self.pos = {p["po_number"]: PurchaseOrder(p["po_number"], p["supplier_id"], tuple(
            POLine(ln["sku"], ln["description"], ln["qty"], Decimal(ln["unit_price"])) for ln in p["lines"]))
            for p in os_["purchase_orders"]}
        self.received = {g["po_number"]: {ln["sku"]: ln["qty_received"] for ln in g["lines"]}
                         for g in os_["goods_receipts"]}

    def get_po(self, po_number):
        return self.pos.get(po_number)

    def received_qty(self, po_number):
        return dict(self.received.get(po_number, {}))

    def supplier_name(self, supplier_id):
        return supplier_id


def as_extracted(d: dict) -> ExtractedDoc:
    return ExtractedDoc(d["supplier_id"], d["number"], d["doc_type"], d["po_number"], d["issue_date"],
                        Decimal(d["total"]), tuple(DocLine(ln["sku"], ln["qty"], Decimal(ln["unit_price"]))
                                                   for ln in d["lines"]))


@pytest.mark.parametrize("portal", ["a", "b", "c"])
def test_every_verdict_and_amount_matches_ground_truth(portal):
    orders, ledger = MemoryOrderSystem(DATA), Ledger()
    truth = {t["doc_id"]: t for t in DATA["ground_truth"]}
    docs = sorted((d for d in DATA["documents"] if d["portal"] == portal and truth[d["doc_id"]]["in_scope"]),
                  key=lambda d: (d["issue_date"], d["number"]))  # the order an AP clerk works the queue
    for d in docs:
        v = match(as_extracted(d), orders, ledger)
        t = truth[d["doc_id"]]
        assert v.verdict == t["verdict"], (d["number"], v.evidence)
        expected = None if t["expected_payable"] is None else Decimal(t["expected_payable"])
        assert v.payable == expected, (d["number"], v.payable, expected)


def test_tampered_total_goes_to_a_human():
    orders, d = MemoryOrderSystem(DATA), next(x for x in DATA["documents"] if x["status"] == "open"
                                              and x["doc_type"] == "invoice" and x["po_number"] in DATA_POS)
    doc = as_extracted({**d, "total": str(Decimal(d["total"]) + 1)})
    v = match(doc, orders, Ledger())
    assert v.verdict == "total_mismatch" and v.payable is None


def test_line_not_on_po_goes_to_a_human():
    orders = MemoryOrderSystem(DATA)
    d = next(x for x in DATA["documents"] if x["po_number"] in DATA_POS and x["doc_type"] == "invoice")
    extra = {"sku": "ZZ-999", "description": "x", "qty": 1, "unit_price": "1.00"}
    doc = as_extracted({**d, "lines": d["lines"] + [extra], "total": str(Decimal(d["total"]) + 1)})
    v = match(doc, orders, Ledger())
    assert v.verdict == "line_not_on_po" and v.payable is None


DATA_POS = {p["po_number"] for p in DATA["order_system"]["purchase_orders"]}
