"""Runs, steps and review items in Postgres: what the review console reads, and the audit log (C6).

The agent writes each step as it happens (live replay in the console). Review decisions are recorded here and
nowhere else: approving an item marks it "approved_for_payment" for the AP system; nothing in this project pays.
"""

from __future__ import annotations

import json
from decimal import Decimal

import psycopg
from psycopg.types.json import Jsonb

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS runs (
    run_id      text PRIMARY KEY,
    portal      text NOT NULL,
    chaos       text NOT NULL DEFAULT '',
    status      text NOT NULL DEFAULT 'running',    -- running | done | handoff | budget | error
    reason      text NOT NULL DEFAULT '',
    downloads   integer NOT NULL DEFAULT 0,
    calls       integer NOT NULL DEFAULT 0,
    seconds     numeric(8,1),
    started_at  timestamptz NOT NULL DEFAULT now(),
    finished_at timestamptz
);
CREATE TABLE IF NOT EXISTS steps (
    run_id      text NOT NULL REFERENCES runs ON DELETE CASCADE,
    idx         integer NOT NULL,
    n           integer NOT NULL,
    action      jsonb NOT NULL,
    ok          boolean NOT NULL,
    result      text NOT NULL,
    screenshot  text NOT NULL DEFAULT '',
    created_at  timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (run_id, idx)
);
CREATE TABLE IF NOT EXISTS review_items (
    item_id      serial PRIMARY KEY,
    run_id       text NOT NULL REFERENCES runs ON DELETE CASCADE,
    number       text NOT NULL,
    status       text NOT NULL,       -- proposed | needs_human | approved_for_payment | rejected
    verdict      text NOT NULL,
    payable      numeric(12,2),
    evidence     jsonb NOT NULL,
    portal_check text NOT NULL,
    decided_by   text,
    decision_note text,
    decided_at   timestamptz,
    UNIQUE (run_id, number)
);
"""


class RunStore:
    def __init__(self, conn: psycopg.Connection):
        self.conn = conn
        conn.execute(SCHEMA_SQL)

    def start(self, run_id: str, portal: str, chaos: str = "") -> None:
        self.conn.execute("INSERT INTO runs (run_id, portal, chaos) VALUES (%s, %s, %s) ON CONFLICT DO NOTHING",
                          (run_id, portal, chaos))

    def step(self, run_id: str, idx: int, n: int, action: dict, ok: bool, result: str, screenshot: str) -> None:
        self.conn.execute("INSERT INTO steps VALUES (%s, %s, %s, %s, %s, %s, %s) ON CONFLICT DO NOTHING",
                          (run_id, idx, n, Jsonb(action), ok, result, screenshot))

    def finish(self, run_id: str, status: str, reason: str, downloads: int, calls: int, seconds: float) -> None:
        self.conn.execute("""UPDATE runs SET status=%s, reason=%s, downloads=%s, calls=%s, seconds=%s,
                             finished_at=now() WHERE run_id=%s""", (status, reason, downloads, calls, seconds, run_id))

    def save_review(self, run_id: str, items: list) -> None:
        with self.conn.transaction():
            self.conn.execute("DELETE FROM review_items WHERE run_id=%s AND decided_at IS NULL", (run_id,))
            for i in items:
                self.conn.execute(
                    """INSERT INTO review_items (run_id, number, status, verdict, payable, evidence, portal_check)
                       VALUES (%s, %s, %s, %s, %s, %s, %s) ON CONFLICT (run_id, number) DO NOTHING""",
                    (run_id, i.number, i.status, i.verdict, None if i.payable is None else Decimal(i.payable),
                     Jsonb(i.evidence), i.portal_check))

    def decide(self, item_id: int, decision: str, who: str, note: str = "") -> dict | None:
        if decision not in ("approve", "reject"):
            raise ValueError("decision must be approve or reject")
        status = "approved_for_payment" if decision == "approve" else "rejected"
        row = self.conn.execute(
            """UPDATE review_items SET status=%s, decided_by=%s, decision_note=%s, decided_at=now()
               WHERE item_id=%s AND decided_at IS NULL RETURNING item_id, number, status""",
            (status, who, note, item_id)).fetchone()
        return dict(row) if row else None


def jsonable(rows: list[dict]) -> list[dict]:
    return json.loads(json.dumps(rows, default=str))
