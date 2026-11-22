"""Job task 6 (Databricks): the weekly brief's numbers (D19), on the replay day that closes a week (Sunday).

Code computes every number, as in the app's brief: the week's volume, the invoices the model scored and flagged
(threshold at 80% precision, fixed on the calibration month), the EUR on them, and the vendors with the most flagged
money. The written summary is not produced here: it needs the LLM and the grounding check, which stay in the app.
On other days the task records nothing and succeeds.
"""

import json
from pathlib import Path

import mlflow
from pyspark.sql import SparkSession

spark = SparkSession.builder.getOrCreate()
DBT = "workspace.p2p_autopilot_dbt"
RAW = "workspace.p2p_autopilot_raw"
MODEL = "models:/workspace.p2p_autopilot.payment_block@champion"

import sys
from datetime import date


def write_brief(day: date) -> None:
    mlflow.set_registry_uri("databricks-uc")
    cal = json.loads(next(Path(mlflow.artifacts.download_artifacts(MODEL)).rglob("calibration*.json")).read_text())
    thr = cal["threshold_at_precision_0.8"]
    start = f"DATE_SUB(DATE'{day}', 6)"
    week = spark.sql(f"""
        SELECT sum(CASE WHEN e.activity = 'Create Purchase Order Item' THEN 1 ELSE 0 END) AS lines_ordered,
               sum(CASE WHEN e.activity = 'Record Invoice Receipt' THEN 1 ELSE 0 END)     AS invoices_recorded,
               sum(CASE WHEN e.activity = 'Clear Invoice' THEN 1 ELSE 0 END)              AS payments,
               round(sum(CASE WHEN e.activity = 'Clear Invoice' THEN c.value_eur END))    AS eur_paid
        FROM {DBT}.events e JOIN {DBT}.cases c ON c.case_id = e.case_id
        WHERE e.is_canonical AND CAST(e.ts AS DATE) BETWEEN {start} AND DATE'{day}'""").first().asDict()
    risk = spark.sql(f"""
        SELECT count(*) AS lines_scored, sum(CASE WHEN p_block >= {thr} THEN 1 ELSE 0 END) AS lines_flagged,
               round(sum(CASE WHEN p_block >= {thr} THEN greatest(value_eur, 0) END)) AS eur_flagged
        FROM {DBT}.worklist_daily WHERE day BETWEEN {start} AND DATE'{day}'""").first().asDict()
    vendors = [r.asDict() for r in spark.sql(f"""
        SELECT vendor, count(*) AS lines_flagged, round(sum(greatest(value_eur, 0))) AS eur_flagged
        FROM {DBT}.worklist_daily WHERE day BETWEEN {start} AND DATE'{day}' AND p_block >= {thr}
        GROUP BY vendor ORDER BY eur_flagged DESC LIMIT 5""").collect()]
    numbers = {"week": week, "block_risk": {**risk, "threshold": thr}, "top_vendors": vendors}
    spark.sql(f"CREATE TABLE IF NOT EXISTS {DBT}.weekly_brief (week_end DATE, numbers STRING, computed_at TIMESTAMP)")
    spark.sql(f"DELETE FROM {DBT}.weekly_brief WHERE week_end = DATE'{day}'")
    (spark.createDataFrame([(day, json.dumps(numbers, default=float))], "week_end DATE, numbers STRING")
     .selectExpr("*", "current_timestamp() AS computed_at").write.mode("append").saveAsTable(f"{DBT}.weekly_brief"))
    print(f"week ending {day}: {json.dumps(numbers, default=float)}")


# the replay day, or a week-end date given as a parameter (to re-run or test one week)
day = date.fromisoformat(sys.argv[1]) if len(sys.argv) > 1 else \
    spark.sql(f"SELECT max(day) AS d FROM {RAW}.replay_state").first()["d"]
if day.isoweekday() == 7:
    write_brief(day)
else:
    print(f"{day}: not the end of a week, no brief")
