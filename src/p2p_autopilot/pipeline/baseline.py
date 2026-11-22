"""Phase 0 of the data layer: freeze what the current Python build produces, before dbt replaces it.

Rebuilds the warehouse from the raw CSV with the existing code (warehouse.py), builds the invoice-time feature
frame the payment-block model uses (predict.build_frame), and records a fingerprint of every table plus the
daily-worklist numbers behind the CV claim. The dbt build must reproduce these exactly (pipeline/parity.py).

Usage: python -m p2p_autopilot.pipeline.baseline   (~2 min)
"""

from __future__ import annotations

import json

import duckdb
import pandas as pd

from p2p_autopilot.pipeline.fingerprint import fingerprint
from p2p_autopilot.pipeline.paths import BASELINE as OUT
from p2p_autopilot.pipeline.paths import LEGACY_DB
from p2p_autopilot.process import predict
from p2p_autopilot.process.warehouse import DEFAULT_CSV, DEFAULT_DB, ROOT, build

TABLES = ["events", "cases", "cycles", "waits", "dq_report"]


def legacy_features(con: duckdb.DuckDBPyConnection) -> None:
    frame = predict.build_frame(con, "invoice", until="2100-01-01")
    df = pd.DataFrame({k: list(v) for k, v in frame.items()})
    con.register("frame_df", df)
    con.execute("CREATE OR REPLACE TABLE invoice_features AS SELECT * FROM frame_df")
    con.unregister("frame_df")


def main() -> None:
    LEGACY_DB.parent.mkdir(parents=True, exist_ok=True)
    build(DEFAULT_CSV, LEGACY_DB)
    con = duckdb.connect(str(LEGACY_DB))
    legacy_features(con)
    out = {"source_csv": DEFAULT_CSV.name, "tables": {t: fingerprint(con, t) for t in [*TABLES, "invoice_features"]}}
    con.close()
    baked = duckdb.connect(str(DEFAULT_DB), read_only=True)
    out["baked_worklist"] = fingerprint(baked, "m_block_risk")
    baked.close()
    report = predict.business_report(LEGACY_DB)
    out["daily_worklist"] = report["daily_worklist"]
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(json.dumps(out, indent=1) + "\n")
    for t, f in out["tables"].items():
        print(f"  {t:<18} {f['rows']:>10,} rows  {f['md5'][:12]}")
    print("daily worklist:", {k: v for k, v in out["daily_worklist"].items() if k.startswith("top10")})
    print(f"-> {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
