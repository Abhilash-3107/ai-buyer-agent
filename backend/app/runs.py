"""One fresh database file per run, so eval repeats keep their evidence and parallel runs never collide."""
from __future__ import annotations

import secrets
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from .db import DATA_DIR
from .scenarios import SCENARIOS
from .seed import build_scenario_db

RUNS_DIR = DATA_DIR / "runs"


@dataclass(frozen=True)
class Run:
    run_id: str
    scenario_id: str
    node_id: str  # the one node this run may read and write, taken from the trigger
    path: Path


def _trigger_node(conn: sqlite3.Connection, trigger: dict) -> str:
    """Every trigger is about one node; find it in the data instead of hard-coding it."""
    kind = trigger["type"]
    if kind == "DEMAND_ALERT":
        return trigger["node_id"]
    if kind == "RECOMMENDATION_REVIEW":
        row = conn.execute("SELECT node_id FROM recommendations WHERE rec_id = ?", (trigger["rec_id"],)).fetchone()
    elif kind == "SUPPLIER_EVENT":
        row = conn.execute("SELECT po.node_id FROM supplier_events e JOIN purchase_orders po ON po.po_id = e.po_id "
                           "WHERE e.event_id = ?", (trigger["event_id"],)).fetchone()
    else:
        raise ValueError(f"Unknown trigger type {kind!r}")
    if row is None:
        raise ValueError(f"Trigger {trigger} points at nothing in the database")
    return row[0]


def new_run(scenario_id: str, *, in_memory: bool = False) -> tuple[Run, sqlite3.Connection]:
    """Build data/runs/<scenario>__<run_id>.db (or an in-memory DB) and record the run_id in meta."""
    run_id = f"{datetime.now(UTC):%Y%m%dT%H%M%S}-{secrets.token_hex(3)}"
    path = Path(":memory:") if in_memory else RUNS_DIR / f"{scenario_id}__{run_id}.db"
    conn = build_scenario_db(scenario_id, path)
    conn.execute("INSERT INTO meta VALUES ('run_id', ?)", (run_id,))
    conn.commit()
    node_id = _trigger_node(conn, SCENARIOS[scenario_id].trigger)
    return Run(run_id, scenario_id, node_id, path), conn
