"""The client's order system: purchase orders and goods receipts, behind a small interface (decision D3).

`OrderSystem` is what the matching code depends on. `PostgresOrderSystem` is today's backend; an Odoo adapter can
implement the same three methods later without touching the matcher (the same pattern my Order Ops Agent uses for tau2 vs Shopify).
Money is NUMERIC(12,2) in the database and Decimal in Python, never float.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from decimal import Decimal
from typing import Protocol

import psycopg
from psycopg.rows import dict_row

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS suppliers (
    supplier_id  text PRIMARY KEY,
    name         text NOT NULL
);
CREATE TABLE IF NOT EXISTS purchase_orders (
    po_number    text PRIMARY KEY,
    supplier_id  text NOT NULL REFERENCES suppliers,
    order_date   date NOT NULL
);
CREATE TABLE IF NOT EXISTS po_lines (
    po_number    text NOT NULL REFERENCES purchase_orders,
    sku          text NOT NULL,
    description  text NOT NULL,
    qty          integer NOT NULL CHECK (qty > 0),
    unit_price   numeric(12,2) NOT NULL CHECK (unit_price >= 0),
    PRIMARY KEY (po_number, sku)
);
CREATE TABLE IF NOT EXISTS goods_receipts (
    gr_number     text PRIMARY KEY,
    po_number     text NOT NULL REFERENCES purchase_orders,
    received_date date NOT NULL
);
CREATE TABLE IF NOT EXISTS paid_invoices (   -- the AP ledger: what has already been paid
    supplier_id  text NOT NULL REFERENCES suppliers,
    number       text NOT NULL,
    amount       numeric(12,2) NOT NULL,
    PRIMARY KEY (supplier_id, number)
);
CREATE TABLE IF NOT EXISTS gr_lines (
    gr_number     text NOT NULL REFERENCES goods_receipts,
    sku           text NOT NULL,
    qty_received  integer NOT NULL CHECK (qty_received >= 0),
    PRIMARY KEY (gr_number, sku)
);
"""


@dataclass(frozen=True)
class POLine:
    sku: str
    description: str
    qty: int
    unit_price: Decimal


@dataclass(frozen=True)
class PurchaseOrder:
    po_number: str
    supplier_id: str
    lines: tuple[POLine, ...]


class OrderSystem(Protocol):
    def get_po(self, po_number: str) -> PurchaseOrder | None: ...
    def received_qty(self, po_number: str) -> dict[str, int]: ...
    def supplier_name(self, supplier_id: str) -> str | None: ...
    def is_paid(self, supplier_id: str, number: str) -> bool: ...


def connect(url: str | None = None) -> psycopg.Connection:
    url = url or os.environ.get("DATABASE_URL")
    if not url:
        raise RuntimeError("Set DATABASE_URL in .env (see .env.example).")
    return psycopg.connect(url, autocommit=True, connect_timeout=10, row_factory=dict_row)


def load(conn: psycopg.Connection, data: dict) -> dict[str, int]:
    """Replace the order system with the generated data. Idempotent: safe to run twice."""
    os_ = data["order_system"]
    with conn.transaction():
        conn.execute(SCHEMA_SQL)
        conn.execute("TRUNCATE paid_invoices, gr_lines, goods_receipts, po_lines, purchase_orders, suppliers")
        with conn.cursor() as cur:
            cur.executemany("INSERT INTO suppliers VALUES (%s, %s)", [(s["id"], s["name"]) for s in data["suppliers"]])
            cur.executemany("INSERT INTO purchase_orders VALUES (%s, %s, %s)",
                            [(p["po_number"], p["supplier_id"], p["order_date"]) for p in os_["purchase_orders"]])
            cur.executemany("INSERT INTO po_lines VALUES (%s, %s, %s, %s, %s)",
                            [(p["po_number"], ln["sku"], ln["description"], ln["qty"], ln["unit_price"])
                             for p in os_["purchase_orders"] for ln in p["lines"]])
            cur.executemany("INSERT INTO goods_receipts VALUES (%s, %s, %s)",
                            [(g["gr_number"], g["po_number"], g["received_date"]) for g in os_["goods_receipts"]])
            cur.executemany("INSERT INTO paid_invoices VALUES (%s, %s, %s)",
                            [(d["supplier_id"], d["number"], d["total"]) for d in data["documents"]
                             if d["status"] == "paid"])
            cur.executemany("INSERT INTO gr_lines VALUES (%s, %s, %s)",
                            [(g["gr_number"], ln["sku"], ln["qty_received"])
                             for g in os_["goods_receipts"] for ln in g["lines"]])
    return {t: conn.execute(f"SELECT count(*) AS n FROM {t}").fetchone()["n"]
            for t in ("suppliers", "purchase_orders", "po_lines", "goods_receipts", "gr_lines", "paid_invoices")}


class PostgresOrderSystem:
    def __init__(self, conn: psycopg.Connection):
        self.conn = conn

    def get_po(self, po_number: str) -> PurchaseOrder | None:
        rows = self.conn.execute(
            """SELECT p.po_number, p.supplier_id, l.sku, l.description, l.qty, l.unit_price
               FROM purchase_orders p JOIN po_lines l USING (po_number)
               WHERE p.po_number = %s ORDER BY l.sku""", (po_number,)).fetchall()
        if not rows:
            return None
        return PurchaseOrder(rows[0]["po_number"], rows[0]["supplier_id"],
                             tuple(POLine(r["sku"], r["description"], r["qty"], r["unit_price"]) for r in rows))

    def received_qty(self, po_number: str) -> dict[str, int]:
        rows = self.conn.execute(
            """SELECT l.sku, sum(l.qty_received)::int AS qty
               FROM goods_receipts g JOIN gr_lines l USING (gr_number)
               WHERE g.po_number = %s GROUP BY l.sku""", (po_number,)).fetchall()
        return {r["sku"]: r["qty"] for r in rows}

    def is_paid(self, supplier_id: str, number: str) -> bool:
        return self.conn.execute("SELECT 1 FROM paid_invoices WHERE supplier_id=%s AND number=%s",
                                 (supplier_id, number)).fetchone() is not None

    def supplier_name(self, supplier_id: str) -> str | None:
        row = self.conn.execute("SELECT name FROM suppliers WHERE supplier_id = %s", (supplier_id,)).fetchone()
        return row["name"] if row else None


if __name__ == "__main__":
    from dotenv import load_dotenv

    from p2p_autopilot.data.generate import generate

    load_dotenv()
    with connect() as c:
        print("loaded:", load(c, generate()))
