"""Step 1 of the daily pipeline: land the SAP extract as files, the way a customer's export job would drop them.

The BPI 2019 log arrives as one CSV. A real feed would deliver a backfill of history plus one file per day, each row
carrying a stable source key. This step simulates that, with no change to the data:
  - file_row: the row's position in the delivered CSV (the warehouse's event_id, D7), so every target warehouse
    numbers events the same way;
  - extract_date: the day the row would have been extracted: the event's date when it is a valid date, otherwise the
    first valid date of its PO line (an out-of-range date is a typo entered together with the rest of the line, D1).

Modes:
  --full                   one file with every row (dbt parity against the legacy build)
  --replay-start D [--until E]   history before D as backfill.csv.gz, then one file per day D..E (the replay feeds
                           the test months day by day, so no later event, and no later label, exists before its day)

Files: <out>/sap_events_backfill.csv.gz, <out>/sap_events_YYYY-MM-DD.csv.gz (all columns text, as delivered).
Usage: python -m p2p_autopilot.data_layer.land --full [--out DIR]
"""

from __future__ import annotations

import argparse
from datetime import date, timedelta
from pathlib import Path

import duckdb

from p2p_autopilot.data_layer.paths import LANDING
from p2p_autopilot.process.warehouse import DEFAULT_CSV, VALID_FROM, VALID_TO


def stage(con: duckdb.DuckDBPyConnection, csv: Path) -> None:
    con.execute("""
        CREATE TEMP TABLE delivered AS
        SELECT row_number() OVER () AS file_row, * FROM read_csv(?, all_varchar = true)
    """, [str(csv)])
    con.execute(f"""
        CREATE TEMP TABLE landed AS
        WITH d AS (
            SELECT *, TRY_CAST(left(timestamp, 10) AS DATE) AS ev_date FROM delivered),
        v AS (
            SELECT *, ev_date >= DATE '{VALID_FROM}' AND ev_date < DATE '{VALID_TO}' AS valid FROM d),
        first_valid AS (
            SELECT case_id, min(ev_date) AS first_day FROM v WHERE valid GROUP BY 1)
        SELECT v.file_row,
               CAST(CASE WHEN v.valid THEN v.ev_date ELSE coalesce(f.first_day, DATE '{VALID_FROM}') END AS VARCHAR)
                   AS extract_date,
               v.* EXCLUDE (file_row, ev_date, valid)
        FROM v LEFT JOIN first_valid f USING (case_id)
    """)


def write(con: duckdb.DuckDBPyConnection, where: str, path: Path) -> int:
    n = con.execute(f"SELECT count(*) FROM landed WHERE {where}").fetchone()[0]
    if n:
        con.execute(f"COPY (SELECT * FROM landed WHERE {where} ORDER BY file_row) TO '{path}' "
                    "(FORMAT csv, HEADER, COMPRESSION gzip)")
    return n


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", type=Path, default=DEFAULT_CSV)
    ap.add_argument("--out", type=Path, default=LANDING)
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--full", action="store_true")
    g.add_argument("--replay-start", type=date.fromisoformat)
    ap.add_argument("--until", type=date.fromisoformat, help="last day file to write (default: last day in the data)")
    a = ap.parse_args()
    a.out.mkdir(parents=True, exist_ok=True)
    for old in a.out.glob("sap_events_*.csv.gz"):
        old.unlink()
    con = duckdb.connect()
    stage(con, a.csv)
    if a.full:
        n = write(con, "true", a.out / "sap_events_backfill.csv.gz")
        print(f"landed {n:,} rows in one file -> {a.out}")
        return
    start = a.replay_start
    end = a.until or date.fromisoformat(con.execute("SELECT max(extract_date) FROM landed").fetchone()[0])
    n = write(con, f"extract_date < '{start}'", a.out / "sap_events_backfill.csv.gz")
    print(f"backfill: {n:,} rows before {start}")
    day, files = start, 0
    while day <= end:
        files += bool(write(con, f"extract_date = '{day}'", a.out / f"sap_events_{day}.csv.gz"))
        day += timedelta(days=1)
    print(f"{files} daily files {start}..{end} -> {a.out}")


if __name__ == "__main__":
    main()
