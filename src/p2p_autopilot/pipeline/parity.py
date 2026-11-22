"""Parity: do the dbt-built tables equal the legacy Python build (pipeline/baseline.json), row for row?

Compares fingerprints (same columns, in the baseline's order). When a table differs and the legacy DuckDB file is
present (runs/data_layer/legacy.duckdb, written by baseline.py), it also counts the rows on each side that the other
side lacks, per column, so a mismatch points at its cause.

Usage: python -m p2p_autopilot.pipeline.parity [--db runs/data_layer/dbt.duckdb]   (exit 1 on any mismatch)
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import duckdb

from p2p_autopilot.pipeline.fingerprint import fingerprint, normalized_select
from p2p_autopilot.pipeline.paths import BASELINE, DBT_DB, LEGACY_DB

KEYS = {"events": ["event_id"], "cases": ["case_id"], "cycles": ["case_id", "cycle_no"],
        "waits": ["case_id", "to_seq"], "dq_report": ["check_name"], "invoice_features": ["case_id"]}


def explain(con: duckdb.DuckDBPyConnection, table: str, cols: list[str]) -> None:
    new = normalized_select(con, f"{con.execute('SELECT current_database()').fetchone()[0]}.main.{table}", cols)
    old = normalized_select(con, f"legacy.main.{table}", cols)
    keys = KEYS[table]
    only_new = con.execute(f"SELECT count(*) FROM ({new} EXCEPT ALL {old})").fetchone()[0]
    only_old = con.execute(f"SELECT count(*) FROM ({old} EXCEPT ALL {new})").fetchone()[0]
    print(f"    rows only in dbt: {only_new:,}, only in legacy: {only_old:,}")
    join = " AND ".join(f'n."{k}" IS NOT DISTINCT FROM o."{k}"' for k in keys)
    for c in cols:
        if c in keys:
            continue
        n = con.execute(f'SELECT count(*) FROM ({new}) n JOIN ({old}) o ON {join} '
                        f'WHERE n."{c}" IS DISTINCT FROM o."{c}"').fetchone()[0]
        if n:
            ex = con.execute(f'SELECT {", ".join(f"n.{k}" for k in keys)}, n."{c}", o."{c}" FROM ({new}) n '
                             f'JOIN ({old}) o ON {join} WHERE n."{c}" IS DISTINCT FROM o."{c}" LIMIT 3').fetchall()
            print(f"    column {c}: {n:,} rows differ, e.g. (key, dbt, legacy) {ex}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", type=Path, default=DBT_DB)
    a = ap.parse_args()
    base = json.loads(BASELINE.read_text())["tables"]
    con = duckdb.connect(str(a.db), read_only=True)
    if LEGACY_DB.exists():
        con.execute(f"ATTACH '{LEGACY_DB}' AS legacy (READ_ONLY)")
    bad = 0
    for table, b in base.items():
        f = fingerprint(con, f"{con.execute('SELECT current_database()').fetchone()[0]}.main.{table}", b["columns"])
        ok = f["rows"] == b["rows"] and f["md5"] == b["md5"] and f["columns"] == b["columns"]
        bad += not ok
        print(f"  {table:<18} {f['rows']:>10,} rows  {'MATCH' if ok else 'DIFFERENT'}"
              + ("" if f["columns"] == b["columns"] else f"  missing columns {set(b['columns']) - set(f['columns'])}"))
        if not ok and LEGACY_DB.exists() and f["columns"] == b["columns"]:
            explain(con, table, b["columns"])
    print("parity: " + ("100%" if not bad else f"{bad} table(s) differ"))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
