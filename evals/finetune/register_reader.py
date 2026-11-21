"""Log a Kaggle fine-tuning run to MLflow and apply the registry gate (DECISIONS D28).

The Kaggle job trains and writes its outputs; this script, run on the laptop with full registry rights, is the gate:
    1. downloads the job's outputs (or reads a folder),
    2. logs one MLflow run: settings, the loss curve, timings, library versions, Kaggle kernel version, dataset hash,
       held-out-50 scores for the untuned and the fine-tuned model, and the adapter,
    3. registers the adapter as a version of workspace.p2p_autopilot.receipt_reader and moves @champion to it only
       if it beats the untuned model on the held-out 50 (total and date, adjusted). Test scores are not used here.

    uv run --group mlops python evals/finetune/register_reader.py --kernel jpreyesm03/p2p-receipt-reader-qlora
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import tempfile
from pathlib import Path

os.environ.setdefault("MLFLOW_DISABLE_AGENT_HINT", "1")
os.environ.setdefault("DATABRICKS_CONFIG_PROFILE", "p2p")

import mlflow
from mlflow import MlflowClient

from score import DATA, labels, load, summarize

ROOT = Path(__file__).resolve().parents[2]
EXPERIMENT = "/Shared/p2p-autopilot/receipt-reader"
MODEL_NAME = "workspace.p2p_autopilot.receipt_reader"


class ReaderAdapter(mlflow.pyfunc.PythonModel):
    """Registry entry for a LoRA adapter: loads the 4-bit base model plus the adapter on a GPU machine."""

    def load_context(self, context):
        from unsloth import FastVisionModel
        cfg = json.loads(Path(context.artifacts["run_info"]).read_text())
        self.model, self.tok = FastVisionModel.from_pretrained(context.artifacts["adapter"], load_in_4bit=True)
        FastVisionModel.for_inference(self.model)
        self.base = cfg["model"]

    def predict(self, context, model_input, params=None):
        raise NotImplementedError("batch reading runs in the Kaggle job; this entry versions the adapter")


def dataset_hash() -> str:
    h = hashlib.sha256()
    for name in ("train.jsonl", "val.jsonl", "splits.json"):
        h.update((DATA / name).read_bytes())
    return h.hexdigest()[:16]


def kernel_version(kernel: str) -> str:
    out = subprocess.run(["uvx", "--python", "3.12", "--with", "six", "--from", "kaggle>=1.8", "kaggle", "kernels",
                          "status", kernel], capture_output=True, text=True).stdout
    return out.strip().splitlines()[-1] if out else "unknown"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--kernel", default="jpreyesm03/p2p-receipt-reader-qlora")
    ap.add_argument("--outputs", type=Path, default=ROOT / "runs" / "finetune" / "kaggle_out")
    ap.add_argument("--no-download", action="store_true")
    a = ap.parse_args()

    if not a.no_download:
        a.outputs.mkdir(parents=True, exist_ok=True)
        subprocess.run(["uvx", "--python", "3.12", "--with", "six", "--from", "kaggle>=1.8", "kaggle", "kernels",
                        "output", a.kernel, "-p", str(a.outputs), "-o"], check=True, capture_output=True)
    info = json.loads((a.outputs / "run_info.json").read_text())
    if info.get("smoke"):
        raise SystemExit("smoke-test outputs: not logged or registered")
    log = json.loads((a.outputs / "train_log.json").read_text())

    gt = labels("val")
    base = summarize(load(a.outputs / "preds_base_val.jsonl"), gt, sorted(gt))
    ft = summarize(load(a.outputs / "preds_ft_val.jsonl"), gt, sorted(gt))
    keys = ("total_adjusted", "date", "total_and_date", "company", "address_fuzzy", "parsed")

    mlflow.set_tracking_uri(os.environ.get("MLFLOW_TRACKING_URI", "databricks"))
    mlflow.set_registry_uri(os.environ.get("MLFLOW_REGISTRY_URI", "databricks-uc"))
    mlflow.set_experiment(EXPERIMENT)
    client = MlflowClient()
    with mlflow.start_run(run_name=f"qlora-r{info['lora_r']}-e{info['epochs']}") as run:
        mlflow.log_params({k: info[k] for k in ("model", "lora_r", "lora_alpha", "epochs", "lr", "grad_accum",
                                                "max_len", "seed")})
        mlflow.log_params({"train_steps": info.get("train_steps"), "gpu": info.get("gpu"),
                           **{f"v_{k}": v for k, v in info.get("versions", {}).items()}})
        mlflow.set_tags({"kaggle.kernel": a.kernel, "kaggle.status": kernel_version(a.kernel),
                         "data.sha256_16": dataset_hash(), "decision": "D28", "trained_on": "Kaggle T4 (free)"})
        for row in log:
            if "loss" in row:
                mlflow.log_metric("train_loss", row["loss"], step=int(row["step"]))
        mlflow.log_metrics({f"val_base_{k}": base[k] for k in keys} | {f"val_ft_{k}": ft[k] for k in keys})
        mlflow.log_metrics({f"seconds_{k}": v for k, v in info["timings_s"].items()}
                           | {"peak_gpu_gb": info.get("peak_gpu_gb", 0)})
        mlflow.log_artifact(str(a.outputs / "run_info.json"))
        mlflow.log_artifact(str(a.outputs / "train_log.json"))
        logged = mlflow.pyfunc.log_model(
            name="reader", python_model=ReaderAdapter(),
            artifacts={"adapter": str(a.outputs / "adapter"), "run_info": str(a.outputs / "run_info.json")},
            pip_requirements=[f"{p}=={v}" for p, v in info.get("versions", {}).items()],
            signature=mlflow.models.infer_signature(["receipt.jpg"], ['{"total": "1.00"}']))

    passes = ft["total_and_date"] > base["total_and_date"] and ft["date"] >= base["date"] \
        and ft["total_adjusted"] >= base["total_adjusted"]
    why = (f"held-out 50: total+date {ft['total_and_date']} vs untuned {base['total_and_date']}; total "
           f"{ft['total_adjusted']} vs {base['total_adjusted']}; date {ft['date']} vs {base['date']}")
    mv = mlflow.register_model(logged.model_uri, MODEL_NAME)
    client.set_model_version_tag(MODEL_NAME, mv.version, "gate", ("PROMOTED: " if passes else "REJECTED: ") + why)
    client.set_model_version_tag(MODEL_NAME, mv.version, "run_id", run.info.run_id)
    if passes:
        client.set_registered_model_alias(MODEL_NAME, "champion", mv.version)
    print(f"run {run.info.run_id[:8]} -> {MODEL_NAME} v{mv.version}: {'PROMOTED' if passes else 'REJECTED'} ({why})")


if __name__ == "__main__":
    main()
