"""Load the landed SAP extract into Snowflake (raw schema), as delivered: PUT the gzipped CSV files to an internal
stage and COPY INTO a table of text columns. Same files as DuckDB and Databricks read.

Usage: python data_layer/snowflake/load.py [--landing runs/landing/sap_events]
"""

import argparse
import time
from pathlib import Path

from conn import connect

from p2p_autopilot.data_layer.paths import LANDING

COLUMNS = ["file_row", "extract_date", "case_id", "activity", "timestamp", "resource", "user", "cum_net_worth_eur",
           "event_id", "case_purchasing_document", "case_item", "case_item_type", "case_item_category",
           "case_gr_based_inv_verif", "case_goods_receipt", "case_source", "case_purch_doc_category_name",
           "case_company", "case_spend_classification_text", "case_spend_area_text", "case_sub_spend_area_text",
           "case_vendor", "case_name", "case_document_type"]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--landing", type=Path, default=LANDING)
    a = ap.parse_args()
    t0 = time.monotonic()
    c = connect().cursor()
    c.execute("CREATE SCHEMA IF NOT EXISTS P2P.P2P_AUTOPILOT_RAW")
    c.execute("USE SCHEMA P2P.P2P_AUTOPILOT_RAW")
    c.execute("CREATE OR REPLACE FILE FORMAT sap_csv TYPE = CSV SKIP_HEADER = 1 FIELD_OPTIONALLY_ENCLOSED_BY = '\"' "
              "COMPRESSION = GZIP EMPTY_FIELD_AS_NULL = TRUE NULL_IF = ()")
    c.execute("CREATE OR REPLACE STAGE landing FILE_FORMAT = sap_csv")
    cols = ", ".join(f'"{x.upper()}" VARCHAR' for x in COLUMNS)
    c.execute(f"CREATE OR REPLACE TABLE sap_events ({cols})")
    for f in sorted(a.landing.glob("sap_events_*.csv.gz")):
        c.execute(f"PUT 'file://{f}' @landing AUTO_COMPRESS = FALSE OVERWRITE = TRUE")
    c.execute("COPY INTO sap_events FROM @landing PATTERN = '.*sap_events_.*[.]csv[.]gz' ON_ERROR = ABORT_STATEMENT")
    n = c.execute("SELECT count(*) FROM sap_events").fetchone()[0]
    print(f"loaded {n:,} rows into P2P.P2P_AUTOPILOT_RAW.SAP_EVENTS in {time.monotonic() - t0:.0f}s")


if __name__ == "__main__":
    main()
