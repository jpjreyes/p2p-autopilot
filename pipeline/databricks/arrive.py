"""Job task 1 (Databricks): the next day's SAP extract arrives in the landing volume.

Replay of the test months (data-layer decision 4): every file the customer will send is staged once in the feed
volume; each run moves the backfill (first run) or the next day's file into landing, and records the day in a state
table. Nothing later than that day exists in landing, so nothing later can reach the warehouse.
"""

import shutil
import sys
from datetime import date, timedelta
from pathlib import Path

from pyspark.sql import SparkSession

spark = SparkSession.builder.getOrCreate()
RAW = "workspace.p2p_autopilot_raw"
FEED = Path("/Volumes/workspace/p2p_autopilot_raw/feed")
LANDING = Path("/Volumes/workspace/p2p_autopilot_raw/landing")
START = date.fromisoformat(sys.argv[1] if len(sys.argv) > 1 else "2018-09-01")

spark.sql(f"CREATE TABLE IF NOT EXISTS {RAW}.replay_state (day DATE, arrived_at TIMESTAMP, file STRING)")
last = spark.sql(f"SELECT max(day) AS d FROM {RAW}.replay_state").first()["d"]
if last is None:
    shutil.copy(FEED / "sap_events_backfill.csv.gz", LANDING / "sap_events_backfill.csv.gz")
    day, name = START - timedelta(days=1), "sap_events_backfill.csv.gz"
else:
    day = last + timedelta(days=1)
    name = f"sap_events_{day}.csv.gz"
    if (FEED / name).exists():
        shutil.copy(FEED / name, LANDING / name)
    else:
        name = None  # no extract that day (weekend or holiday): the pipeline still runs and scores nothing
spark.sql(f"INSERT INTO {RAW}.replay_state VALUES (DATE'{day}', current_timestamp(), "
          f"{repr(name) if name else 'NULL'})")
print(f"arrived: {name or 'nothing'} for {day}")
