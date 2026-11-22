"""Parity: the tables dbt built on Snowflake from the full extract must equal, row for row, the original Python build
(data_layer/baseline.json). Reads each table as Arrow into DuckDB (column names lower-cased) and compares the same
order-independent fingerprints as the DuckDB and Databricks checks. Also records build timings for the README.

Usage: python data_layer/snowflake/parity.py
"""

import json
import time

import duckdb
from conn import connect

from p2p_autopilot.data_layer.fingerprint import fingerprint
from p2p_autopilot.data_layer.paths import BASELINE, DATA_LAYER


def main() -> None:
    base = json.loads(BASELINE.read_text())["tables"]
    c = connect("P2P_AUTOPILOT_DBT").cursor()
    mirror_db = DATA_LAYER / "parity_snowflake.duckdb"
    mirror_db.unlink(missing_ok=True)
    m = duckdb.connect(str(mirror_db))
    m.execute("SET TimeZone = 'UTC'")
    bad = 0
    for t, b in base.items():
        t0 = time.monotonic()
        arrow = c.execute(f"SELECT * FROM {t}").fetch_arrow_all()
        arrow = arrow.rename_columns([x.lower() for x in arrow.column_names])
        m.register("a", arrow)
        m.execute(f"CREATE TABLE {t} AS SELECT * FROM a")
        m.unregister("a")
        f = fingerprint(m, t, b["columns"])
        ok = f["rows"] == b["rows"] and f["md5"] == b["md5"]
        bad += not ok
        print(f"  {t:<18} {f['rows']:>10,} rows  {'MATCH' if ok else 'DIFFERENT'}  ({time.monotonic() - t0:.0f}s)")
    print("Snowflake vs original Python build: " + ("100%" if not bad else f"{bad} table(s) differ"))
    raise SystemExit(1 if bad else 0)


if __name__ == "__main__":
    main()
