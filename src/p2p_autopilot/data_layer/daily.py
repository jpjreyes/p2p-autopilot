"""The daily pipeline's steps, callable one at a time, so any orchestrator can run them (Airflow locally; the Databricks
job runs the same steps with Databricks-native ingestion). State lives in a home directory:

  <home>/landing/        files that have arrived (backfill + one per replay day)
  <home>/state.json      the last replay day processed
  <home>/warehouse.duckdb  the dbt build
  <home>/worklist.jsonl  one scored line per row: {"day", "case_id", "p_block", "model"}

Steps:
  arrive   move the backfill (first run) or the next day's file from the feed into landing; advance the cursor
  build    dbt build (models + tests) on DuckDB from the landed files
  score    score the day's new invoices with the committed production model (= registry @champion v1)
  check    the day's lines were scored exactly once (no duplicates when a step is retried)

Usage: python -m p2p_autopilot.data_layer.daily <step> --home DIR [--start 2018-09-01]
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from datetime import date, timedelta
from pathlib import Path

import duckdb

from p2p_autopilot.data_layer.paths import DATA_LAYER, DBT_DIR
from p2p_autopilot.data_layer.score import Scorer, columns_of

FEED = DATA_LAYER / "replay_feed"  # written by `land --replay-start` (the replay module stages it)


def _state(home: Path) -> dict:
    p = home / "state.json"
    return json.loads(p.read_text()) if p.exists() else {}


def arrive(home: Path, start: date) -> None:
    landing = home / "landing"
    landing.mkdir(parents=True, exist_ok=True)
    st = _state(home)
    if "day" not in st:
        shutil.copy(FEED / "sap_events_backfill.csv.gz", landing)
        day = start - timedelta(days=1)
    else:
        day = date.fromisoformat(st["day"]) + timedelta(days=1)
        f = FEED / f"sap_events_{day}.csv.gz"
        if f.exists():
            shutil.copy(f, landing)
    (home / "state.json").write_text(json.dumps({"day": str(day)}))
    print(f"arrived: data for {day}")


def build(home: Path) -> None:
    env = {**os.environ, "P2P_DUCKDB": str(home / "warehouse.duckdb"), "P2P_LANDING": str(home / "landing")}
    subprocess.run(["dbt", "build", "--project-dir", str(DBT_DIR), "--profiles-dir", str(DBT_DIR), "--quiet"],
                   env=env, check=True)
    print("dbt build: models and tests passed")


def score(home: Path) -> None:
    day = date.fromisoformat(_state(home)["day"])
    con = duckdb.connect(str(home / "warehouse.duckdb"), read_only=True)
    rel = con.execute("SELECT * FROM invoice_features WHERE CAST(ir_ts AS DATE) = ?", [day])
    frame = columns_of(rel.fetchall(), [d[0] for d in rel.description])
    con.close()
    p = Scorer()(frame)
    out = home / "worklist.jsonl"
    kept = [r for r in (json.loads(x) for x in out.read_text().splitlines())] if out.exists() else []
    kept = [r for r in kept if r["day"] != str(day)]  # a retry replaces the day, never doubles it
    kept += [{"day": str(day), "case_id": c, "p_block": round(float(s), 9), "model": "block-invoice"}
             for c, s in zip(frame["case_id"], p)]
    out.write_text("".join(json.dumps(r) + "\n" for r in kept))
    print(f"{day}: {len(p)} invoiced lines scored")


def check(home: Path) -> None:
    day = _state(home)["day"]
    rows = [json.loads(x) for x in (home / "worklist.jsonl").read_text().splitlines()] \
        if (home / "worklist.jsonl").exists() else []
    ids = [r["case_id"] for r in rows if r["day"] == day]
    if len(ids) != len(set(ids)):
        raise SystemExit(f"{day}: a line was scored twice")
    print(f"{day}: check passed ({len(ids)} lines, no duplicates)")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("step", choices=["arrive", "build", "score", "check"])
    ap.add_argument("--home", type=Path, required=True)
    ap.add_argument("--start", type=date.fromisoformat, default=date(2018, 9, 1))
    a = ap.parse_args()
    {"arrive": lambda: arrive(a.home, a.start), "build": lambda: build(a.home),
     "score": lambda: score(a.home), "check": lambda: check(a.home)}[a.step]()


if __name__ == "__main__":
    sys.exit(main())
