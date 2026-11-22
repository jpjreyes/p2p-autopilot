"""Parity between warehouses: the dbt tables Databricks built must equal, row for row, a local DuckDB build from the
same landed files (the backfill plus every daily file up to the job's replay day), and the job's scores must equal
the local scorer's on the same day.

Reads the Databricks tables through the SQL warehouse into DuckDB and compares fingerprints with the same
normalization as pipeline/parity.py.

Usage: python pipeline/databricks/parity.py   (dbt group; profile `p2p`; downloads ~1.6M rows, a few minutes)
"""

import os
import shutil
import subprocess
import time
from datetime import date, timedelta

import duckdb
import pyarrow as pa
import pyarrow.ipc
import requests
from databricks.sdk import WorkspaceClient
from databricks.sdk.service.sql import Disposition, Format, StatementState

from p2p_autopilot.pipeline.fingerprint import fingerprint
from p2p_autopilot.pipeline.paths import DATA_LAYER, DBT_DIR
from p2p_autopilot.pipeline.score import Scorer, columns_of

TABLES = ["events", "cases", "cycles", "waits", "dq_report", "invoice_features"]
FEED = DATA_LAYER / "replay_feed"


class Warehouse:
    """Queries through the SQL Statement Execution API (REST), results as Arrow chunks behind presigned links."""

    def __init__(self) -> None:
        self.w = WorkspaceClient(profile="p2p")
        self.id = next(x.id for x in self.w.warehouses.list() if x.name == "Serverless Starter Warehouse")

    def arrow(self, statement: str) -> pa.Table:
        se = self.w.statement_execution
        r = se.execute_statement(warehouse_id=self.id, statement=statement, wait_timeout="50s",
                                 disposition=Disposition.EXTERNAL_LINKS, format=Format.ARROW_STREAM)
        while r.status.state in (StatementState.PENDING, StatementState.RUNNING):
            time.sleep(2)
            r = se.get_statement(r.statement_id)
        if r.status.state != StatementState.SUCCEEDED:
            raise RuntimeError(f"{statement[:60]}: {r.status.state} {r.status.error}")
        tables = []
        for i in range(r.manifest.total_chunk_count or 0):
            links = r.result.external_links if i == 0 and r.result else \
                se.get_statement_result_chunk_n(r.statement_id, i).external_links
            for link in links:
                body = requests.get(link.external_link, timeout=120).content
                tables.append(pa.ipc.open_stream(body).read_all())
        return pa.concat_tables(tables) if tables else pa.table({})

    def rows(self, statement: str) -> list[tuple]:
        t = self.arrow(statement)
        return list(zip(*[t.column(i).to_pylist() for i in range(t.num_columns)])) if t.num_columns else []


def main() -> None:
    remote = Warehouse()
    day = remote.rows("SELECT max(day) FROM workspace.p2p_autopilot_raw.replay_state")[0][0]
    print(f"Databricks replay day: {day}")
    local_landing = DATA_LAYER / "parity_landing"
    shutil.rmtree(local_landing, ignore_errors=True)
    local_landing.mkdir(parents=True)
    shutil.copy(FEED / "sap_events_backfill.csv.gz", local_landing)
    d = date(2018, 9, 1)
    while d <= day:
        if (FEED / f"sap_events_{d}.csv.gz").exists():
            shutil.copy(FEED / f"sap_events_{d}.csv.gz", local_landing)
        d += timedelta(days=1)
    local_db = DATA_LAYER / "parity_local.duckdb"
    local_db.unlink(missing_ok=True)
    subprocess.run(["dbt", "run", "--project-dir", str(DBT_DIR), "--profiles-dir", str(DBT_DIR), "--quiet"],
                   env={**os.environ, "P2P_DUCKDB": str(local_db), "P2P_LANDING": str(local_landing)}, check=True)
    mirror_db = DATA_LAYER / "parity_databricks.duckdb"
    mirror_db.unlink(missing_ok=True)
    mirror = duckdb.connect(str(mirror_db))
    for t in TABLES:
        arrow = remote.arrow(f"SELECT * FROM workspace.p2p_autopilot_dbt.{t}")
        mirror.register("a", arrow)
        mirror.execute(f"CREATE TABLE {t} AS SELECT * FROM a")
        mirror.unregister("a")
    local = duckdb.connect(str(local_db), read_only=True)
    bad = 0
    for t in TABLES:
        cols = [c for c, in local.execute(f"SELECT column_name FROM information_schema.columns WHERE table_name = '{t}' "
                                          "ORDER BY ordinal_position").fetchall()]
        a, b = fingerprint(local, t, cols), fingerprint(mirror, t, cols)
        ok = a["md5"] == b["md5"] and a["rows"] == b["rows"]
        bad += not ok
        print(f"  {t:<18} DuckDB {a['rows']:>10,}  Databricks {b['rows']:>10,}  {'MATCH' if ok else 'DIFFERENT'}")
    # scores: the job's champion from the registry vs the committed model file, same day, same features
    job = dict(remote.rows(f"SELECT case_id, p_block FROM workspace.p2p_autopilot_dbt.worklist_daily "
                           f"WHERE day = DATE'{day}'"))
    rel = local.execute("SELECT * FROM invoice_features WHERE CAST(ir_ts AS DATE) = ?", [day])
    frame = columns_of(rel.fetchall(), [x[0] for x in rel.description])
    mine = dict(zip(frame["case_id"], Scorer()(frame)))
    diff = max((abs(job[k] - mine[k]) for k in mine if k in job), default=0.0)
    same_set = set(job) == set(mine)
    print(f"  scores {day}: job {len(job)} lines, local {len(mine)}, same lines {same_set}, max |diff| {diff:.2e}")
    bad += (not same_set) or diff > 1e-9
    print("warehouse parity: " + ("100%" if not bad else "DIFFERENT"))
    raise SystemExit(1 if bad else 0)


if __name__ == "__main__":
    main()
