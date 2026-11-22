"""Leak check: build the warehouse from only the data landed up to a cutoff day and compare every invoice's features
with the full-data build. A feature that changes once later data arrives was using the future.

Rules (exit 1 if any fails):
  1. Every feature column is identical for invoices recorded before the cutoff, except the known, documented
     pre-existing exceptions below, each within its bound.
  2. Every row a retrain may use at the cutoff (dbt model training_rows) has the same label as in the full data:
     no label is used before it is observable (D18 label delay).
  3. dbt's own tests pass on the cutoff build (including: no test-month row in training_rows).

Usage: python -m p2p_autopilot.data_layer.leak_check [--cutoff 2018-09-15]   (needs the dbt dependency group)
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from datetime import date, timedelta

import duckdb

from p2p_autopilot.data_layer.paths import DATA_LAYER, DBT_DIR

# known pre-existing exceptions in the D18 features, with the share of rows allowed to differ (data-layer D31):
#   po_lines counts every line of the PO, including lines created after the invoice;
#   n_vendor_invoice can move when a later event changes a line's timeline and so a D1 date repair.
ALLOWED = {"po_lines": 0.02, "n_vendor_invoice": 0.001}


def build(name: str, landing_args: list[str]) -> str:
    landing = DATA_LAYER / f"landing_{name}"
    db = DATA_LAYER / f"{name}.duckdb"
    db.unlink(missing_ok=True)
    subprocess.run([sys.executable, "-m", "p2p_autopilot.data_layer.land", *landing_args, "--out", str(landing)],
                   check=True)
    env = {**os.environ, "P2P_DUCKDB": str(db), "P2P_LANDING": str(landing)}
    r = subprocess.run(["dbt", "build", "--project-dir", str(DBT_DIR), "--profiles-dir", str(DBT_DIR), "--quiet"],
                       env=env, check=False)
    if r.returncode:
        raise SystemExit(f"dbt build failed on the {name} build")
    return str(db)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cutoff", type=date.fromisoformat, default=date(2018, 9, 15))
    a = ap.parse_args()
    DATA_LAYER.mkdir(parents=True, exist_ok=True)
    full = build("leak_full", ["--full"])
    cut = build("leak_cut", ["--replay-start", "2018-09-01", "--until", str(a.cutoff)])
    con = duckdb.connect(cut, read_only=True)
    con.execute(f"ATTACH '{full}' AS allrows (READ_ONLY)")
    end = a.cutoff + timedelta(days=1)
    cols = con.execute("""SELECT column_name, data_type FROM information_schema.columns
                          WHERE table_catalog = 'leak_cut' AND table_name = 'invoice_features'
                          ORDER BY ordinal_position""").fetchall()
    n = con.execute(f"SELECT count(*) FROM main.invoice_features WHERE ir_ts < '{end}'").fetchone()[0]
    missing = con.execute(f"""SELECT count(*) FROM allrows.main.invoice_features WHERE ir_ts < '{end}'
                              AND case_id NOT IN (SELECT case_id FROM main.invoice_features)""").fetchone()[0]
    failures = [f"{missing} invoices before the cutoff are missing from the cutoff build"] if missing else []
    print(f"cutoff {a.cutoff}: {n:,} invoiced lines recorded before it")
    for c, t in cols:
        if c in ("case_id", "label"):
            continue
        differs = f"round(a.{c}, 9) IS DISTINCT FROM round(b.{c}, 9)" if t == "DOUBLE" \
            else f"CAST(a.{c} AS VARCHAR) IS DISTINCT FROM CAST(b.{c} AS VARCHAR)"
        k = con.execute(f"""SELECT count(*) FROM main.invoice_features a JOIN allrows.main.invoice_features b
                            USING (case_id) WHERE a.ir_ts < '{end}' AND {differs}""").fetchone()[0]
        if not k:
            continue
        share = k / n
        ok = c in ALLOWED and share <= ALLOWED[c]
        print(f"  {c}: {k:,} rows differ ({share:.2%}){' known exception, within bound' if ok else ''}")
        if not ok:
            failures.append(f"feature {c} changes when later data arrives ({k:,} rows)")
    train = con.execute("SELECT count(*) FROM main.training_rows").fetchone()[0]
    bad_label = con.execute("""SELECT count(*) FROM main.training_rows a JOIN allrows.main.invoice_features b
                               USING (case_id) WHERE a.label <> b.label""").fetchone()[0]
    pending = con.execute(f"""SELECT count(*) FROM main.invoice_features a JOIN allrows.main.invoice_features b
                              USING (case_id) WHERE a.ir_ts < '{end}' AND a.label <> b.label""").fetchone()[0]
    print(f"  labels: {pending:,} not yet observable at the cutoff; {train:,} rows eligible for training, "
          f"{bad_label} of them with a label that later changes")
    if bad_label:
        failures.append(f"{bad_label} training rows use a label that was not yet observable")
    print("leak check: " + ("PASS" if not failures else "FAIL\n  " + "\n  ".join(failures)))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
