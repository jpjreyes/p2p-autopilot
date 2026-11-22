"""Job task 4 (Databricks): score the day's new invoices with the @champion payment-block model from the Unity
Catalog registry and write them to the daily worklist (one row per PO line; an invoice's risk = its riskiest line).
Same feature encoding as p2p_autopilot.process.predict.matrix (categorical codes saved with the model, D29).
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

mlflow.set_registry_uri("databricks-uc")
day = spark.sql(f"SELECT max(day) AS d FROM {RAW}.replay_state").first()["d"]
version = mlflow.MlflowClient().get_model_version_by_alias("workspace.p2p_autopilot.payment_block", "champion").version
# the champion's own files (booster + calibration, logged in D29), loaded directly: no pickled Python code to unpickle
local = Path(mlflow.artifacts.download_artifacts(MODEL))
cal = json.loads(next(local.rglob("calibration*.json")).read_text())
booster = lgb.Booster(model_file=str(next(local.rglob("booster*.txt"))))
rows = spark.sql(f"SELECT * FROM {DBT}.invoice_features WHERE CAST(ir_ts AS DATE) = DATE'{day}'").toPandas()
spark.sql(f"CREATE TABLE IF NOT EXISTS {DBT}.worklist_daily (day DATE, case_id STRING, vendor STRING, "
          "ir_ts TIMESTAMP, value_eur DOUBLE, p_block DOUBLE, model_version STRING, scored_at TIMESTAMP)")
spark.sql(f"DELETE FROM {DBT}.worklist_daily WHERE day = DATE'{day}'")  # a rerun replaces the day, never doubles it
if len(rows):
    cat = np.column_stack([[cal["codes"][c].get(v, 0) for v in rows[c]] for c in CATEGORICAL])
    num = rows[[f for f in cal["features"] if f not in CATEGORICAL]].astype(float).to_numpy()
    p = np.interp(booster.predict(np.hstack([cat, num]).astype(float)), cal["iso_x"], cal["iso_y"])
    out = rows[["case_id", "vendor", "ir_ts", "value_eur"]].copy()
    out["p_block"], out["day"], out["model_version"] = p, day, str(version)
    (spark.createDataFrame(out).selectExpr("day", "case_id", "vendor", "ir_ts", "value_eur", "p_block",
                                           "model_version", "current_timestamp() AS scored_at")
     .write.mode("append").saveAsTable(f"{DBT}.worklist_daily"))
print(f"{day}: {len(rows)} invoiced lines scored with payment_block v{version}")
