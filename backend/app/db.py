"""SQLite access + the frozen simulation clock.

Design choice: every scenario run gets its OWN fresh SQLite file, seeded from a
known snapshot. The agent's writes (new POs, escalations) can never leak into
another scenario, and every eval run starts from identical data.
"""
from __future__ import annotations

import json
import sqlite3
from datetime import date, timedelta
from pathlib import Path

SCHEMA_PATH = Path(__file__).with_name("schema.sql")

# Frozen "today" so demand windows, lead times and arrival dates are reproducible.
SIM_TODAY = date(2026, 11, 11)


def day(offset: int) -> str:
    """ISO date `offset` days from simulated today (negative = past)."""
    return (SIM_TODAY + timedelta(days=offset)).isoformat()


def offset(iso_date: str) -> int:
    """Days from simulated today to an ISO date (negative = past); the inverse of `day`."""
    return (date.fromisoformat(iso_date) - SIM_TODAY).days


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


def current_run_id(conn: sqlite3.Connection) -> str | None:
    row = conn.execute("SELECT value FROM meta WHERE key = 'run_id'").fetchone()
    return row[0] if row else None


def audit(conn: sqlite3.Connection, run_id: str | None, actor: str, action: str,
          entity_id: str | None, details: dict) -> None:
    """Append one row to the audit trail. The caller owns the transaction."""
    conn.execute(
        "INSERT INTO audit_log (run_id, actor, action, entity_id, details_json, created_at) VALUES (?, ?, ?, ?, ?, ?)",
        (run_id, actor, action, entity_id, json.dumps(details, default=str), day(0)))
