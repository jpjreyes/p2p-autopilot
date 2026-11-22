"""Step 4 of the daily pipeline: score the day's new invoices with the payment-block model.

Input: rows of the dbt model invoice_features (any warehouse, read into columns). Output: one score per PO line and
the day's worklist (invoices ranked by their riskiest line). The model is the committed production model
(data/models/block-invoice.*, the same version registered as @champion in D29); on Databricks the job loads the
champion from the Unity Catalog registry instead and must give the same scores (parity).
"""

from __future__ import annotations

import json

import lightgbm as lgb
import numpy as np

from p2p_autopilot.process.predict import MODELS, matrix


class Scorer:
    def __init__(self, name: str = "block-invoice") -> None:
        self.booster = lgb.Booster(model_file=str(MODELS / f"{name}.txt"))
        self.meta = json.loads((MODELS / f"{name}.json").read_text())

    def __call__(self, frame: dict[str, np.ndarray]) -> np.ndarray:
        if not len(frame["case_id"]):
            return np.array([])
        X, _, _ = matrix(frame, self.meta["codes"])
        return np.interp(self.booster.predict(X), self.meta["iso_x"], self.meta["iso_y"])


def columns_of(rows: list[tuple], names: list[str]) -> dict[str, np.ndarray]:
    return {c: np.array([r[i] for r in rows], dtype=object) for i, c in enumerate(names)}
