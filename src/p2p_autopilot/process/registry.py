"""The payment-block model in an MLflow registry, with a champion/challenger gate and a drift report (D29).

Each candidate is trained by the same code as D18 (`predict.run`, production files untouched), logged as an MLflow
run (parameters, development-month metrics, baselines, data fingerprint) and registered as a version of one model.
The gate rule is written before it runs:
    promote the challenger to @champion only if, on the August 2018 development month, its average precision is at
    least 0.005 higher than the champion's AND its Brier score is no more than 0.002 worse.
The Sep-Nov test months are never used to choose (their labels are not read here). The drift report compares the
training months' features and scores with the test months' (inputs only, no labels).

Run (needs the warehouse and an MLflow server; Databricks profile `p2p` by default):
    uv run --group mlops python -m p2p_autopilot.process.registry
Point it elsewhere with MLFLOW_TRACKING_URI / MLFLOW_REGISTRY_URI (e.g. a self-hosted MLflow).
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path

os.environ.setdefault("MLFLOW_DISABLE_AGENT_HINT", "1")
os.environ.setdefault("DATABRICKS_CONFIG_PROFILE", "p2p")

import mlflow
import numpy as np
import pandas as pd
from mlflow import MlflowClient
from mlflow.models import infer_signature

from p2p_autopilot.process import predict
from p2p_autopilot.process.warehouse import DEFAULT_DB

EXPERIMENT = "/Shared/p2p-autopilot/payment-block"
CATALOG, SCHEMA = "workspace", "p2p_autopilot"
MODEL_NAME = f"{CATALOG}.{SCHEMA}.payment_block"
GATE = {"min_ap_gain": 0.005, "max_brier_loss": 0.002}

CANDIDATES = {
    # the production configuration (D18b: conservative trees)
    "v2-conservative": {},
    # the configuration D18b replaced: bigger trees, no regularization
    "v2-default-trees": {"num_leaves": 31, "min_data_in_leaf": 100, "lambda_l2": 0},
}


class BlockModel(mlflow.pyfunc.PythonModel):
    """LightGBM booster + isotonic calibration: returns the calibrated probability of a payment block."""

    def load_context(self, context):
        import lightgbm as lgb
        self.booster = lgb.Booster(model_file=context.artifacts["booster"])
        cal = json.loads(Path(context.artifacts["calibration"]).read_text())
        self.iso_x, self.iso_y = np.array(cal["iso_x"]), np.array(cal["iso_y"])

    def predict(self, context, model_input, params=None):
        raw = self.booster.predict(np.asarray(model_input, dtype=float))
        return np.interp(raw, self.iso_x, self.iso_y)


def fingerprint(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()[:16]


def setup() -> MlflowClient:
    mlflow.set_tracking_uri(os.environ.get("MLFLOW_TRACKING_URI", "databricks"))
    mlflow.set_registry_uri(os.environ.get("MLFLOW_REGISTRY_URI", "databricks-uc"))
    if mlflow.get_tracking_uri().startswith("databricks"):
        from databricks.sdk import WorkspaceClient
        w = WorkspaceClient()
        w.workspace.mkdirs(str(Path(EXPERIMENT).parent))
        if SCHEMA not in [s.name for s in w.schemas.list(catalog_name=CATALOG)]:
            w.schemas.create(name=SCHEMA, catalog_name=CATALOG, comment="P2P Autopilot models")
    mlflow.set_experiment(EXPERIMENT)
    return MlflowClient()


def train_and_log(name: str, overrides: dict, data_fp: str) -> tuple[dict, str]:
    print(f"training candidate {name} ...", flush=True)
    rep = predict.run("invoice", final=False, params=overrides, save=False)
    art = rep.pop("_artifacts")
    m = rep["model"]
    X_dev = pd.DataFrame(art["X"]["scored"], columns=art["features"])
    with mlflow.start_run(run_name=name) as run, tempfile.TemporaryDirectory() as tmp:
        mlflow.log_params({**predict.PARAMS, **overrides, "checkpoint": "invoice", "trees": rep["trees"]})
        mlflow.log_metrics({"dev_avg_precision": m["avg_precision"], "dev_roc_auc": m["roc_auc"],
                            "dev_brier": m["brier"], "dev_recall_at_p80": m["at_precision_0.8"]["recall"],
                            "dev_recall_at_p60": m["at_precision_0.6"]["recall"],
                            "baseline_invoice_rule_ap": rep["baseline_rule_any_line_before_gr"]["avg_precision"],
                            "baseline_vendor_rate_ap": rep["baseline_vendor_rate"]["avg_precision"]})
        mlflow.set_tags({"data.warehouse_sha256_16": data_fp, "scored_on": rep["scored_on"],
                         "decision": "D29", "model.family": "lightgbm+isotonic"})
        mlflow.log_dict({k: v for k, v in rep.items()}, "report.json")
        booster, cal = Path(tmp) / "booster.txt", Path(tmp) / "calibration.json"
        art["model"].save_model(str(booster), num_iteration=art["model"].best_iteration)
        cal.write_text(json.dumps({"iso_x": art["iso"].X_thresholds_.tolist(), "iso_y": art["iso"].y_thresholds_.tolist(),
                                   "codes": art["codes"], "features": art["features"],
                                   "threshold_at_precision_0.8": art["threshold_at_precision_0.8"]}))
        sample = X_dev.head(5)
        info = mlflow.pyfunc.log_model(
            name="model", python_model=BlockModel(), artifacts={"booster": str(booster), "calibration": str(cal)},
            input_example=sample, signature=infer_signature(sample, art["p_scored"][:5]),
            pip_requirements=["lightgbm==4.7.0", "numpy<3", "pandas<3"])
        print(f"  dev AP {m['avg_precision']}  AUC {m['roc_auc']}  Brier {m['brier']}  run {run.info.run_id[:8]}", flush=True)
        return {**rep, "_art": art, "run_id": run.info.run_id}, info.model_uri


def register(client: MlflowClient, model_uri: str, run_id: str) -> str:
    mv = mlflow.register_model(model_uri, MODEL_NAME)
    client.set_model_version_tag(MODEL_NAME, mv.version, "run_id", run_id)
    return mv.version


def gate(champ: dict, chall: dict) -> tuple[bool, str]:
    a, b = champ["model"], chall["model"]
    ap_gain, brier_loss = b["avg_precision"] - a["avg_precision"], b["brier"] - a["brier"]
    ok = ap_gain >= GATE["min_ap_gain"] and brier_loss <= GATE["max_brier_loss"]
    why = (f"challenger dev AP {b['avg_precision']} vs champion {a['avg_precision']} (gain {ap_gain:+.3f}, needs "
           f">= {GATE['min_ap_gain']}); Brier {b['brier']} vs {a['brier']} (change {brier_loss:+.4f}, allowed <= "
           f"{GATE['max_brier_loss']})")
    return ok, why


def drift_report(champ: dict, client: MlflowClient) -> dict:
    """Training months vs test months: features and the champion's scores (no labels)."""
    from evidently import DataDefinition, Dataset, Report
    from evidently.presets import DataDriftPreset

    art = champ["_art"]
    rep = predict.run("invoice", final=True, save=False)  # same features on the test months; labels unused here
    cur_art = rep.pop("_artifacts")
    cols = art["features"]
    iso, booster = art["iso"], art["model"]
    ref = pd.DataFrame(art["X"]["train"], columns=cols)
    ref["score"] = iso.predict(booster.predict(art["X"]["train"]))
    cur = pd.DataFrame(cur_art["X"]["scored"], columns=cols)
    cur["score"] = iso.predict(booster.predict(cur_art["X"]["scored"]))
    ref = ref.sample(min(len(ref), 20000), random_state=7)
    definition = DataDefinition(categorical_columns=predict.CATEGORICAL,
                                numerical_columns=[c for c in cols if c not in predict.CATEGORICAL] + ["score"])
    snap = Report([DataDriftPreset()]).run(Dataset.from_pandas(cur, data_definition=definition),
                                           Dataset.from_pandas(ref, data_definition=definition))
    result = snap.dict()
    share, per_column = None, {}
    for metric in result.get("metrics", []):
        name, cfg, value = metric.get("metric_name", ""), metric.get("config", {}), metric.get("value")
        if name.startswith("DriftedColumnsCount"):
            share = value.get("share")
        elif name.startswith("ValueDrift("):
            # p-value methods drift when the p-value is below the threshold; distance methods when at or above it
            is_p = "p_value" in cfg.get("method", "")
            drifted = value < cfg["threshold"] if is_p else value >= cfg["threshold"]
            per_column[cfg["column"]] = {"method": cfg["method"], "value": round(float(value), 4),
                                         "threshold": cfg["threshold"], "drifted": bool(drifted)}
    drifted = [c for c, v in per_column.items() if v["drifted"]]
    with mlflow.start_run(run_id=champ["run_id"]), tempfile.TemporaryDirectory() as tmp:
        html = Path(tmp) / "drift_train_vs_test.html"
        snap.save_html(str(html))
        mlflow.log_artifact(str(html))
        mlflow.log_dict(result, "drift_train_vs_test.json")
        if share is not None:
            mlflow.log_metric("drift_share_train_vs_test", float(share))
        mlflow.log_metric("drift_score_column_drifted", float(per_column.get("score", {}).get("drifted", False)))
    return {"drifted_share": share, "columns_checked": len(per_column), "drifted_columns": drifted,
            "score": per_column.get("score"), "per_column": per_column,
            "rows": {"reference_train_sample": len(ref), "current_test_months": len(cur)}}


def drift_only() -> None:
    """Recompute the drift report for the current @champion (same code and data as when it was trained)."""
    client = setup()
    mv = client.get_model_version_by_alias(MODEL_NAME, "champion")
    run = client.get_run(mv.run_id)
    overrides = {k: v for k, v in CANDIDATES.get(run.info.run_name, {}).items()}
    rep = predict.run("invoice", final=False, params=overrides, save=False)
    rep["_art"], rep["run_id"] = rep.pop("_artifacts"), mv.run_id
    out = drift_report(rep, client)
    print("drift:", json.dumps({k: v for k, v in out.items() if k != "per_column"}), flush=True)
    path = predict.RUNS / "registry_gate.json"
    summary = json.loads(path.read_text()) if path.exists() else {}
    summary["drift"] = out
    path.write_text(json.dumps(summary, indent=1, default=str))


def main() -> None:
    import sys
    if "--drift-only" in sys.argv:
        return drift_only()
    client = setup()
    data_fp = fingerprint(DEFAULT_DB)
    try:
        current = client.get_model_version_by_alias(MODEL_NAME, "champion")
    except Exception:
        current = None
    summary = {"model": MODEL_NAME, "gate": GATE, "data_fingerprint": data_fp}

    champ, champ_uri = train_and_log("v2-conservative", CANDIDATES["v2-conservative"], data_fp)
    if current is None:
        v = register(client, champ_uri, champ["run_id"])
        client.set_registered_model_alias(MODEL_NAME, "champion", v)
        client.set_model_version_tag(MODEL_NAME, v, "gate", "first version: champion by default")
        summary["champion"] = {"version": v, "run": "v2-conservative", "dev": champ["model"]}
        print(f"registered v{v} as @champion (first version)", flush=True)
    else:
        summary["champion"] = {"version": current.version, "note": "existing champion kept as the reference"}

    chall, chall_uri = train_and_log("v2-default-trees", CANDIDATES["v2-default-trees"], data_fp)
    v = register(client, chall_uri, chall["run_id"])
    client.set_registered_model_alias(MODEL_NAME, "challenger", v)
    promote, why = gate(champ, chall)
    client.set_model_version_tag(MODEL_NAME, v, "gate", ("PROMOTED: " if promote else "REJECTED: ") + why)
    if promote:
        client.set_registered_model_alias(MODEL_NAME, "champion", v)
    summary["challenger"] = {"version": v, "run": "v2-default-trees", "dev": chall["model"],
                             "promoted": promote, "why": why}
    print(("PROMOTED " if promote else "REJECTED ") + why, flush=True)

    summary["drift"] = drift_report(champ, client)
    print("drift:", json.dumps(summary["drift"]), flush=True)
    out = predict.RUNS / "registry_gate.json"
    out.write_text(json.dumps(summary, indent=1, default=str))
    print(f"saved {out}", flush=True)


if __name__ == "__main__":
    main()
