"""SQLite access + the frozen simulation clock.

Design choice: every scenario run gets its OWN fresh SQLite file, seeded from a
known snapshot. The agent's writes (new POs, escalations) can never leak into
another scenario, and every eval run starts from identical data.
"""
from __future__ import annotations

import sqlite3
from datetime import date, timedelta
from pathlib import Path

SCHEMA_PATH = Path(__file__).with_name("schema.sql")
DATA_DIR = Path(__file__).resolve().parent.parent / "data"

# Frozen "today" so demand windows, lead times and arrival dates are reproducible.
SIM_TODAY = date(2026, 11, 11)


def day(offset: int) -> str:
    """ISO date `offset` days from simulated today (negative = past)."""
    return (SIM_TODAY + timedelta(days=offset)).isoformat()


def connect(path: str | Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(path), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def create_empty_db(path: str | Path) -> sqlite3.Connection:
    """Create a brand-new database with the schema (overwrites any existing file)."""
    if str(path) != ":memory:":
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Path(path).unlink(missing_ok=True)
    conn = connect(path)
    conn.executescript(SCHEMA_PATH.read_text())
    conn.execute("INSERT INTO meta VALUES ('sim_today', ?)", (SIM_TODAY.isoformat(),))
    conn.commit()
    return conn
