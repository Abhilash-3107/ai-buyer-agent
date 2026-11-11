"""Create a fresh, isolated database for one scenario.

    uv run python -m app.seed            # list scenarios
    uv run python -m app.seed S1-MODIFY  # build data/S1-MODIFY.db and print a summary
"""
from __future__ import annotations

import sqlite3
import sys

from .builder import Builder
from .db import DATA_DIR, create_empty_db
from .scenarios import SCENARIOS


def build_scenario_db(scenario_id: str, path: str | None = None) -> sqlite3.Connection:
    if scenario_id not in SCENARIOS:
        raise KeyError(f"Unknown scenario {scenario_id!r}. Known: {', '.join(SCENARIOS)}")
    conn = create_empty_db(path or DATA_DIR / f"{scenario_id}.db")
    SCENARIOS[scenario_id].build(Builder(conn))
    conn.execute("INSERT INTO meta VALUES ('scenario_id', ?)", (scenario_id,))
    conn.commit()
    return conn


def _summary(conn: sqlite3.Connection) -> str:
    tables = ["products", "suppliers", "supplier_products", "inventory", "sales_history", "forecasts",
              "purchase_orders", "recommendations", "supplier_events", "promotions", "budgets"]
    return ", ".join(f"{t}={conn.execute(f'SELECT COUNT(*) FROM {t}').fetchone()[0]}" for t in tables)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        for s in SCENARIOS.values():
            print(f"[{s.group}] {s.id:<22} expect {s.expected.decision:<11} {s.title}")
    else:
        c = build_scenario_db(sys.argv[1])
        print(f"Built {sys.argv[1]}: {_summary(c)}")
