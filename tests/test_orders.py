"""Order system round trip against a real Postgres (skipped when DATABASE_URL is not set)."""

import os
from decimal import Decimal

import pytest

from legacy_portal.data.generate import generate
from legacy_portal.orders.store import PostgresOrderSystem, connect, load

pytestmark = pytest.mark.skipif(not os.environ.get("DATABASE_URL"), reason="needs DATABASE_URL (scripts/dev_db.sh up)")
DATA = generate()


@pytest.fixture(scope="module")
def orders():
    conn = connect()
    load(conn, DATA)
    yield PostgresOrderSystem(conn)
    conn.close()


def test_counts_tie_out_and_load_is_idempotent(orders):
    os_ = DATA["order_system"]
    expected = {"purchase_orders": len(os_["purchase_orders"]),
                "po_lines": sum(len(p["lines"]) for p in os_["purchase_orders"]),
                "goods_receipts": len(os_["goods_receipts"])}
    counts = load(orders.conn, DATA)  # second load
    assert {k: counts[k] for k in expected} == expected


def test_po_values_survive_the_round_trip_exactly(orders):
    for p in DATA["order_system"]["purchase_orders"]:
        po = orders.get_po(p["po_number"])
        assert po is not None and po.supplier_id == p["supplier_id"]
        assert {ln.sku: (ln.qty, ln.unit_price) for ln in po.lines} == \
               {ln["sku"]: (ln["qty"], Decimal(ln["unit_price"])) for ln in p["lines"]}


def test_short_shipments_visible_and_unknown_po_absent(orders):
    short = [t for t in DATA["ground_truth"] if t["verdict"] == "qty_above_received"]
    for t in short:
        po = orders.get_po(t["fields"]["po_number"])
        received = orders.received_qty(po.po_number)
        assert any(received.get(ln.sku, 0) < ln.qty for ln in po.lines)  # no receipt yet counts as 0 (D17)
    for t in (t for t in DATA["ground_truth"] if t["verdict"] == "unknown_po"):
        assert orders.get_po(t["fields"]["po_number"]) is None
