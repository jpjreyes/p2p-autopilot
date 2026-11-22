"""Order-independent table fingerprints, so two builds of the same table can be compared exactly.

A fingerprint is the row count plus an md5 over the sorted md5s of every row. Every numeric column is read as a
double rounded to 9 decimals (an engine may type a count as INT, BIGINT or HUGEINT, and floating sums computed in a
different order differ in the last bits), timestamps as text to the second, everything else as text. Two
tables with the same columns and the same rows get the same fingerprint, whatever the row order or the engine
that built them, as long as the values are read back through DuckDB.
"""

from __future__ import annotations

import duckdb

FLOAT_DIGITS = 9
NUMERIC = {"DOUBLE", "FLOAT", "REAL", "TINYINT", "SMALLINT", "INTEGER", "BIGINT", "HUGEINT", "UTINYINT",
           "USMALLINT", "UINTEGER", "UBIGINT"}


def columns(con: duckdb.DuckDBPyConnection, table: str) -> list[tuple[str, str]]:
    """[catalog.][schema.]table -> [(column, type)] in table order."""
    parts = table.split(".")
    filters = dict(zip(["table_catalog", "table_schema", "table_name"][-len(parts):], parts))
    where = " AND ".join(f"{k} = ?" for k in filters)
    q = f"SELECT column_name, data_type FROM information_schema.columns WHERE {where} ORDER BY ordinal_position"
    return [(c, t) for c, t in con.execute(q, list(filters.values())).fetchall()]


def normalized_select(con: duckdb.DuckDBPyConnection, table: str, only: list[str] | None = None) -> str:
    cols = [(c, t) for c, t in columns(con, table) if only is None or c in only]
    if only is not None:
        cols.sort(key=lambda ct: only.index(ct[0]))
    exprs = []
    for c, t in cols:
        if t in NUMERIC or t.startswith("DECIMAL"):
            exprs.append(f'round(CAST("{c}" AS DOUBLE), {FLOAT_DIGITS}) AS "{c}"')
        elif t.startswith("TIMESTAMP"):
            exprs.append(f'strftime(CAST("{c}" AS TIMESTAMP), \'%Y-%m-%d %H:%M:%S\') AS "{c}"')
        else:
            exprs.append(f'CAST("{c}" AS VARCHAR) AS "{c}"')
    return f"SELECT {', '.join(exprs)} FROM {table}"


def fingerprint(con: duckdb.DuckDBPyConnection, table: str, only: list[str] | None = None) -> dict:
    sel = normalized_select(con, table, only)
    n, h = con.execute(f"""
        SELECT count(*), md5(coalesce(string_agg(r, '' ORDER BY r), ''))
        FROM (SELECT md5(CAST(t AS VARCHAR)) AS r FROM ({sel}) t)
    """).fetchone()
    present = [c for c, _ in columns(con, table)]
    return {"rows": int(n), "md5": h, "columns": [c for c in only if c in present] if only else present}
