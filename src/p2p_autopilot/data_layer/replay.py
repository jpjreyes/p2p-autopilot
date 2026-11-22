"""Replay the test months day by day, the way the daily job sees them: on day D only the files landed up to D exist,
dbt rebuilds the warehouse from them, and the day's new invoices are scored. Score only: nothing retrains during the
replay (the test months never train, data-layer decision 4).

Afterwards, when all outcomes are known, the daily worklist is checked against the claim behind the CV (D18c: of the
10 invoices ranked highest each day, 92% get blocked), computed exactly as predict.business_report does: an invoice's
score is its riskiest line, its label is whether any line got blocked, days with fewer than 20 invoices are skipped.

Usage: python -m p2p_autopilot.data_layer.replay [--start 2018-09-01] [--end 2018-11-18]   (needs the dbt group; ~10 min)
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import time
from datetime import date, timedelta

import duckdb
import numpy as np

from p2p_autopilot.data_layer.paths import DATA_LAYER, DBT_DIR, ROOT
from p2p_autopilot.data_layer.score import Scorer, columns_of

FEED = DATA_LAYER / "replay_feed"        # every file the customer will ever send (staged once)
LANDING = DATA_LAYER / "replay_landing"  # what has arrived so far
DB = DATA_LAYER / "replay.duckdb"
OUT = DATA_LAYER / "replay_scores.jsonl"
RESULT = ROOT / "data_layer" / "replay_result.json"


def run_day(day: date, scorer: Scorer) -> list[dict]:
    src = FEED / f"sap_events_{day}.csv.gz"
    if src.exists():
        shutil.copy(src, LANDING / src.name)
    env = {**os.environ, "P2P_DUCKDB": str(DB), "P2P_LANDING": str(LANDING)}
    subprocess.run(["dbt", "run", "--project-dir", str(DBT_DIR), "--profiles-dir", str(DBT_DIR), "--quiet"],
                   env=env, check=True)
    con = duckdb.connect(str(DB), read_only=True)
    rel = con.execute("SELECT * FROM invoice_features WHERE CAST(ir_ts AS DATE) = ?", [day])
    names = [d[0] for d in rel.description]
    frame = columns_of(rel.fetchall(), names)
    con.close()
    p = scorer(frame)
    return [{"day": str(day), "case_id": c, "vendor": v, "ir_ts": str(t), "p": round(float(s), 6)}
            for c, v, t, s in zip(frame["case_id"], frame["vendor"], frame["ir_ts"], p)]


def evaluate(scores: list[dict], full_db: str) -> dict:
    con = duckdb.connect(full_db, read_only=True)
    label = dict(con.execute("SELECT case_id, label FROM invoice_features").fetchall())
    con.close()
    inv_p: dict[str, float] = {}
    inv_y: dict[str, int] = {}
    day_of: dict[str, str] = {}
    for r in scores:
        k = f"{r['vendor']}|{r['ir_ts']}"
        inv_p[k] = max(inv_p.get(k, 0.0), r["p"])
        inv_y[k] = max(inv_y.get(k, 0), int(label[r["case_id"]]))
        day_of[k] = r["day"]
    by_day: dict[str, list[str]] = {}
    for k, d in day_of.items():
        by_day.setdefault(d, []).append(k)
    top10 = []
    for ks in by_day.values():
        if len(ks) >= 20:
            ranked = sorted(ks, key=lambda k: -inv_p[k])
            top10.append(sum(inv_y[k] for k in ranked[:10]) / 10)
    return {"days_scored": len(by_day), "lines_scored": len(scores), "invoices_scored": len(inv_p),
            "top10_days_measured": len(top10), "top10_precision_mean": round(float(np.mean(top10)), 3),
            "top10_precision_median": round(float(np.median(top10)), 3)}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", type=date.fromisoformat, default=date(2018, 9, 1))
    ap.add_argument("--end", type=date.fromisoformat, default=date(2018, 11, 18))
    ap.add_argument("--full-db", default=str(DATA_LAYER / "dbt.duckdb"), help="full build, for the final labels")
    a = ap.parse_args()
    for d in (FEED, LANDING):
        shutil.rmtree(d, ignore_errors=True)
    subprocess.run(["python", "-m", "p2p_autopilot.data_layer.land", "--replay-start", str(a.start),
                    "--out", str(FEED)], check=True)
    LANDING.mkdir(parents=True)
    shutil.copy(FEED / "sap_events_backfill.csv.gz", LANDING)
    DB.unlink(missing_ok=True)
    scorer, scores = Scorer(), []
    n_days = (a.end - a.start).days + 1
    t0 = time.monotonic()
    with OUT.open("w") as f:
        for i in range(n_days):
            day = a.start + timedelta(days=i)
            rows = run_day(day, scorer)
            scores += rows
            for r in rows:
                f.write(json.dumps(r) + "\n")
            eta = (time.monotonic() - t0) / (i + 1) * (n_days - i - 1) / 60
            print(f"{day}: {len(rows):>5} lines scored  [{i + 1}/{n_days}, ETA {eta:.1f} min]", flush=True)
    result = {"window": f"{a.start}..{a.end}", "model": "data/models/block-invoice (= registry @champion v1)",
              **evaluate(scores, a.full_db),
              "claim_D18c": {"top10_precision_mean": 0.92, "top10_days_measured": 54}}
    RESULT.write_text(json.dumps(result, indent=1) + "\n")
    print(json.dumps(result, indent=1))


if __name__ == "__main__":
    main()
