"""The test data is the eval's ground truth, so its invariants are checked like production data."""

from decimal import Decimal

from legacy_portal.data.generate import INVOICES_PER_SUPPLIER, PAID_PER_SUPPLIER, PLAN, generate

D = generate()
POS = {p["po_number"]: p for p in D["order_system"]["purchase_orders"]}
GRS = {g["po_number"]: g for g in D["order_system"]["goods_receipts"]}
DOCS = {d["doc_id"]: d for d in D["documents"]}
TRUTH = {t["doc_id"]: t for t in D["ground_truth"]}


def test_deterministic():
    assert generate() == D


def test_counts_per_portal():
    for portal in "abcd":
        in_scope = [t for t in TRUTH.values() if t["portal"] == portal and t["in_scope"]]
        assert len(in_scope) == INVOICES_PER_SUPPLIER
        assert sum(not t["in_scope"] for t in TRUTH.values() if t["portal"] == portal) == PAID_PER_SUPPLIER
        planted = sorted(t["verdict"] for t in in_scope if t["verdict"] != "match")
        assert planted == sorted(PLAN)


def test_numbers_unique_and_totals_tie_out():
    numbers = [d["number"] for d in DOCS.values()]
    assert len(numbers) == len(set(numbers))
    for d in DOCS.values():
        lines = sum((Decimal(ln["unit_price"]) * ln["qty"] for ln in d["lines"]), Decimal(0))
        sign = -1 if d["doc_type"] == "credit_note" else 1
        assert Decimal(d["total"]) == (lines * sign).quantize(Decimal("0.01")), d["number"]


def test_expected_payable_recomputed_independently():
    """Recompute every verdict's payable amount from the order system, a second implementation of the rule."""
    for t in TRUTH.values():
        d = DOCS[t["doc_id"]]
        if t["verdict"] in ("match", "price_above_po", "qty_above_received"):
            po, gr = POS[d["po_number"]], GRS[d["po_number"]]
            received = {g["sku"]: g["qty_received"] for g in gr["lines"]}
            expected = sum((Decimal(ln["unit_price"]) * min(ln["qty"], received[ln["sku"]]) for ln in po["lines"]),
                           Decimal(0))
            assert Decimal(t["expected_payable"]) == expected.quantize(Decimal("0.01")), t["number"]
        if t["verdict"] == "match":
            assert Decimal(t["expected_payable"]) == Decimal(d["total"])
        if t["verdict"] in ("price_above_po", "qty_above_received"):
            assert Decimal(t["expected_payable"]) < Decimal(d["total"])


def test_planted_issue_types_are_detectable():
    for t in TRUTH.values():
        d = DOCS[t["doc_id"]]
        if t["verdict"] == "unknown_po":
            assert d["po_number"] not in POS
        if t["verdict"] == "duplicate":
            twins = [o for o in DOCS.values() if o["po_number"] == d["po_number"] and o["doc_id"] != d["doc_id"]
                     and o["total"] == d["total"] and o["doc_type"] == "invoice"]
            assert twins and all(o["issue_date"] < d["issue_date"] for o in twins)
        if t["verdict"] == "credit_note":
            assert d["doc_type"] == "credit_note" and Decimal(d["total"]) < 0
        if t["verdict"] == "already_paid":
            assert d["status"] == "paid"


def test_held_out_portal_is_d_only():
    held = [s["portal"] for s in D["suppliers"] if s["held_out"]]
    assert held == ["d"]  # C was used to find fixes (D10), so D is the fresh held-out
