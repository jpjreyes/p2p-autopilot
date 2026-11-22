"""The same daily pipeline as the Databricks job, as an Airflow DAG: arrive -> build (dbt on DuckDB) -> score -> check.

Each task calls one step of p2p_autopilot.data_layer.daily through `uv run`, so Airflow and the project keep separate
environments and both orchestrators run the same code. One DAG run = one replay day (catchup off: runs are
triggered, or follow the daily schedule). Parity with the Databricks job: data_layer/airflow/parity.py.
"""

from __future__ import annotations

import os
from datetime import datetime

from airflow.providers.standard.operators.bash import BashOperator
from airflow.sdk import DAG

REPO = os.environ.get("P2P_REPO", os.path.expanduser("~/other/p2p-autopilot"))
HOME = os.environ.get("P2P_AIRFLOW_HOME_DATA", f"{REPO}/runs/data_layer/airflow_home")


def step(name: str) -> BashOperator:
    return BashOperator(
        task_id=name,
        bash_command=f"cd {REPO} && uv run --group dbt python -m p2p_autopilot.data_layer.daily {name} --home {HOME}",
        retries=1,
    )


with DAG(
    dag_id="p2p_autopilot_daily",
    description="SAP extract arrives -> dbt build + tests on DuckDB -> score the day's invoices -> check",
    schedule="0 6 * * *",
    start_date=datetime(2026, 11, 1),
    catchup=False,
    max_active_runs=1,
    tags=["p2p-autopilot", "data-layer"],
) as dag:
    step("arrive") >> step("build") >> step("score") >> step("check")
