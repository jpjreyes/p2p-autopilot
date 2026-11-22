"""Where the data layer reads and writes (no heavy imports, so every pipeline step can use it)."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
DBT_DIR = ROOT / "dbt"
DATA_LAYER = ROOT / "runs" / "data_layer"
LANDING = ROOT / "runs" / "landing" / "sap_events"
BASELINE = ROOT / "pipeline" / "baseline.json"
LEGACY_DB = DATA_LAYER / "legacy.duckdb"
DBT_DB = DATA_LAYER / "dbt.duckdb"
