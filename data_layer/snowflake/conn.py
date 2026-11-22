"""Snowflake connection for the parity run (30-day trial, no card). Credentials stay outside the repo:
~/.config/jpreyes/snowflake.env (SNOWFLAKE_ACCOUNT, SNOWFLAKE_USER) and the programmatic access token in
~/.config/jpreyes/snowflake_pat, scoped to role P2P_DBT."""

import os
from pathlib import Path

import snowflake.connector

CFG = Path.home() / ".config" / "jpreyes"


def env() -> dict[str, str]:
    vals = dict(line.split("=", 1) for line in (CFG / "snowflake.env").read_text().split() if "=" in line)
    vals["SNOWFLAKE_PAT"] = (CFG / "snowflake_pat").read_text().strip()
    return vals


def connect(schema: str | None = None):
    e = env()
    return snowflake.connector.connect(account=e["SNOWFLAKE_ACCOUNT"], user=e["SNOWFLAKE_USER"],
                                       password=e["SNOWFLAKE_PAT"], role="P2P_DBT", warehouse="P2P_WH",
                                       database="P2P", schema=schema, login_timeout=30)


def dbt_env() -> dict[str, str]:
    e = env()
    return {**os.environ, "SNOWFLAKE_ACCOUNT": e["SNOWFLAKE_ACCOUNT"], "SNOWFLAKE_USER": e["SNOWFLAKE_USER"],
            "SNOWFLAKE_PAT": e["SNOWFLAKE_PAT"]}
