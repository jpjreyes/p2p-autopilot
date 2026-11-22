"""Order-independent table fingerprints, so two builds of the same table can be compared exactly.

A fingerprint is the row count plus an md5 over the sorted md5s of every row, with DOUBLE columns rounded to 9
decimals (floating sums computed in a different order differ in the last bits) and timestamps as text. Two
tables with the same columns and the same rows get the same fingerprint, whatever the row order or the engine
that built them, as long as the values are read back through DuckDB.
"""

from __future__ import annotations

import duckdb

FLOAT_DIGITS = 9


def columns(con: duckdb.DuckDBPyConnection, table: str) -> list[tuple[str, str]]:
    schema, _, name = table.rpartition(".")
    q = "SELECT column_name, data_type FROM information_schema.columns WHERE table_name = ?"
    args = [name]
    if schema:
        q += " AND table_schema = ?"
        args.append(schema)
    return [(c, t) for c, t in con.execute(q + " ORDER BY ordinal_position", args).fetchall()]


def normalized_select(con: duckdb.DuckDBPyConnection, table: str, only: list[str] | None = None) -> str:
    cols = [(c, t) for c, t in columns(con, table) if only is None or c in only]
    if only is not None:
        cols.sort(key=lambda ct: only.index(ct[0]))
    exprs = []
    for c, t in cols:
        if t in ("DOUBLE", "FLOAT", "REAL") or t.startswith("DECIMAL"):
            exprs.append(f'round(CAST("{c}" AS DOUBLE), {FLOAT_DIGITS}) AS "{c}"')
        elif t.startswith("TIMESTAMP"):
            exprs.append(f'strftime(CAST("{c}" AS TIMESTAMP), \'%Y-%m-%d %H:%M:%S\') AS "{c}"')
        else:
            exprs.append(f'"{c}"')
    return f"SELECT {', '.join(exprs)} FROM {table}"


def fingerprint(con: duckdb.DuckDBPyConnection, table: str, only: list[str] | None = None) -> dict:
    sel = normalized_select(con, table, only)
    n, h = con.execute(f"""
        SELECT count(*), md5(coalesce(string_agg(r, '' ORDER BY r), ''))
        FROM (SELECT md5(CAST(t AS VARCHAR)) AS r FROM ({sel}) t)
    """).fetchone()
    return {"rows": int(n), "md5": h, "columns": [c for c, _ in columns(con, table) if only is None or c in only]}
