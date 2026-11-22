"""Orchestrator parity: the Airflow DAG (local, DuckDB) and the Databricks job must produce the same daily worklist
for every replay day both have processed: the same lines, the same scores.

Usage: python data_layer/airflow/parity.py   (dbt group; profile `p2p`)
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "databricks"))
from parity import Warehouse

from p2p_autopilot.data_layer.paths import DATA_LAYER

HOME = DATA_LAYER / "airflow_home"


def main() -> None:
    local: dict[str, dict[str, float]] = {}
    for line in (HOME / "worklist.jsonl").read_text().splitlines():
        r = json.loads(line)
        local.setdefault(r["day"], {})[r["case_id"]] = r["p_block"]
    remote: dict[str, dict[str, float]] = {}
    for day, case_id, p in Warehouse().rows("SELECT CAST(day AS STRING), case_id, p_block "
                                            "FROM workspace.p2p_autopilot_dbt.worklist_daily"):
        remote.setdefault(day, {})[case_id] = p
    both = sorted(set(local) & set(remote))
    bad = 0
    for d in both:
        a, b = local[d], remote[d]
        diff = max((abs(a[k] - b[k]) for k in a if k in b), default=0.0)
        ok = set(a) == set(b) and diff <= 1e-9
        bad += not ok
        print(f"  {d}: Airflow {len(a):>5} lines, Databricks {len(b):>5}, max |diff| {diff:.1e}  {'MATCH' if ok else 'DIFFERENT'}")
    days_with_lines = sum(1 for d in both if local[d])
    print(f"orchestrator parity: {len(both)} days compared ({days_with_lines} with invoices), "
          + ("100%" if not bad else f"{bad} day(s) differ"))
    raise SystemExit(1 if bad or not both else 0)


if __name__ == "__main__":
    main()
