"""Build a fresh, isolated database for one scenario."""
from __future__ import annotations

import sqlite3
from pathlib import Path

from ..db import create_empty_db
from .builder import Builder
from .catalog import SCENARIOS


def build_scenario_db(scenario_id: str, path: str | Path) -> sqlite3.Connection:
    if scenario_id not in SCENARIOS:
        raise KeyError(f"Unknown scenario {scenario_id!r}. Known: {', '.join(SCENARIOS)}")
    conn = create_empty_db(path)
    SCENARIOS[scenario_id].build(Builder(conn))
    conn.execute("INSERT INTO meta VALUES ('scenario_id', ?)", (scenario_id,))
    conn.commit()
    return conn


def summary(conn: sqlite3.Connection) -> str:
    tables = ["products", "suppliers", "supplier_products", "inventory", "sales_history", "forecasts",
              "purchase_orders", "recommendations", "supplier_events", "promotions", "budgets"]
    return ", ".join(f"{t}={conn.execute(f'SELECT COUNT(*) FROM {t}').fetchone()[0]}" for t in tables)
