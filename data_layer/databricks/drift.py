"""Job task 5 (Databricks): has the input to the model shifted? Population stability index (PSI) of the champion's
score and of its most important features, last 7 replay days vs the July 2018 calibration month (the newest month
the model was fitted on). Written to drift_daily with a status per column: ok (< 0.10), watch (0.10-0.25),
alert (>= 0.25).

Drift is a reason to check performance as soon as the 60-day labels arrive, not a reason to retrain or to stop the
pipeline (D29: 14 of 38 inputs drift between training and test months, yet the model held up). So an alert is
recorded, never a task failure; the job only fails on broken data.
"""

import json
from pathlib import Path

import lightgbm as lgb
import mlflow
import numpy as np
from pyspark.sql import SparkSession

spark = SparkSession.builder.getOrCreate()
DBT = "workspace.p2p_autopilot_dbt"
RAW = "workspace.p2p_autopilot_raw"
MODEL = "models:/workspace.p2p_autopilot.payment_block@champion"
CATEGORICAL = ["item_category", "item_type", "document_type", "spend_area", "sub_spend_area", "company", "ir_user"]
WATCH = ["vendor_block_rate", "inv_any_no_gr", "inv_share_no_gr", "days_po_to_cut", "log_value", "vendor_recent_block_ratio"]
REFERENCE = ("2018-07-01", "2018-08-01")  # calibration month


def psi(ref: np.ndarray, cur: np.ndarray, bins: int = 10) -> float:
    ref, cur = ref[~np.isnan(ref)], cur[~np.isnan(cur)]
    if len(ref) < 50 or len(cur) < 50:
        return float("nan")
    edges = np.unique(np.quantile(ref, np.linspace(0, 1, bins + 1)))
    if len(edges) < 3:  # (near-)constant column: compare the share of each value instead
        vals = np.union1d(np.unique(ref), np.unique(cur))
        r = np.array([(ref == v).mean() for v in vals])
        c = np.array([(cur == v).mean() for v in vals])
    else:
        edges[0], edges[-1] = -np.inf, np.inf
        r = np.histogram(ref, edges)[0] / len(ref)
        c = np.histogram(cur, edges)[0] / len(cur)
    r, c = np.clip(r, 1e-4, None), np.clip(c, 1e-4, None)
    return float(np.sum((c - r) * np.log(c / r)))


mlflow.set_registry_uri("databricks-uc")
day = spark.sql(f"SELECT max(day) AS d FROM {RAW}.replay_state").first()["d"]
local = Path(mlflow.artifacts.download_artifacts(MODEL))
cal = json.loads(next(local.rglob("calibration*.json")).read_text())
booster = lgb.Booster(model_file=str(next(local.rglob("booster*.txt"))))


def frame(where: str):
    rows = spark.sql(f"SELECT * FROM {DBT}.invoice_features WHERE {where}").toPandas()
    if not len(rows):
        return rows, np.array([])
    cat = np.column_stack([[cal["codes"][c].get(v, 0) for v in rows[c]] for c in CATEGORICAL])
    num = rows[[f for f in cal["features"] if f not in CATEGORICAL]].astype(float).to_numpy()
    p = np.interp(booster.predict(np.hstack([cat, num]).astype(float)), cal["iso_x"], cal["iso_y"])
    return rows, p


ref, p_ref = frame(f"ir_ts >= '{REFERENCE[0]}' AND ir_ts < '{REFERENCE[1]}'")
cur, p_cur = frame(f"CAST(ir_ts AS DATE) > DATE_SUB(DATE'{day}', 7) AND CAST(ir_ts AS DATE) <= DATE'{day}'")
results = [("score", psi(p_ref, p_cur))]
for col in WATCH:
    results.append((col, psi(ref[col].astype(float).to_numpy(), cur[col].astype(float).to_numpy()) if len(cur)
                    else float("nan")))

spark.sql(f"CREATE TABLE IF NOT EXISTS {DBT}.drift_daily (day DATE, column_name STRING, psi DOUBLE, status STRING, "
          "rows_current BIGINT, computed_at TIMESTAMP)")
spark.sql(f"DELETE FROM {DBT}.drift_daily WHERE day = DATE'{day}'")
out = []
for col, v in results:
    status = "too few rows" if np.isnan(v) else "alert" if v >= 0.25 else "watch" if v >= 0.10 else "ok"
    out.append((day, col, None if np.isnan(v) else round(v, 4), status, len(cur)))
(spark.createDataFrame(out, "day DATE, column_name STRING, psi DOUBLE, status STRING, rows_current BIGINT")
 .selectExpr("*", "current_timestamp() AS computed_at").write.mode("append").saveAsTable(f"{DBT}.drift_daily"))
print(f"{day}: drift over the last 7 days ({len(cur)} lines) vs July 2018 ({len(ref)} lines): "
      + ", ".join(f"{c} {s}{'' if p is None else f' ({p})'}" for _, c, p, s, _ in out))
