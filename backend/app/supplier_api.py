"""Mock supplier: the only code that knows what a supplier can really ship.

The catalog (what the agent sees) can be stale; the supplier's answer to a submitted PO is the truth.
Deterministic on purpose: the confirmed quantity depends only on the stored availability.
Callers own the transaction, so a failure after `submit` rolls the supplier's answer back too.
"""
from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass

from .db import audit, current_run_id, day

ACTOR = "supplier_api"
EVENT_TYPES = {"CONFIRMED": "CONFIRMATION", "PARTIALLY_CONFIRMED": "PARTIAL_CONFIRMATION", "REJECTED": "REJECTION"}


@dataclass(frozen=True)
class SupplierResponse:
    po_id: str
    requested: int
    confirmed: int
    status: str  # CONFIRMED | PARTIALLY_CONFIRMED | REJECTED
    message: str


def submit(conn: sqlite3.Connection, po_id: str) -> SupplierResponse:
    """Confirm a SUBMITTED PO against live availability and record the answer on the PO, as an event and in the audit log."""
    po = conn.execute("SELECT * FROM purchase_orders WHERE po_id = ?", (po_id,)).fetchone()
    if po is None or po["status"] != "SUBMITTED":
        raise ValueError(f"{po_id} is not a SUBMITTED PO")

    row = conn.execute("SELECT available_units FROM supplier_live_availability WHERE supplier_id = ? AND sku = ?",
                       (po["supplier_id"], po["sku"])).fetchone()
    requested = po["qty_ordered"]
    confirmed = min(requested, row[0] if row else 0)
    if confirmed == requested:
        status, message = "CONFIRMED", f"Supplier confirmed all {requested} units of {po_id}."
    elif confirmed > 0:
        status = "PARTIALLY_CONFIRMED"
        message = (f"Supplier confirmed only {confirmed} of {requested} units of {po_id} "
                   f"(short by {requested - confirmed}).")
    else:
        status, message = "REJECTED", f"Supplier cannot ship any of the {requested} units of {po_id}."

    conn.execute("UPDATE supplier_live_availability SET available_units = available_units - ? "
                 "WHERE supplier_id = ? AND sku = ?", (confirmed, po["supplier_id"], po["sku"]))
    conn.execute("UPDATE purchase_orders SET qty_confirmed = ?, status = ? WHERE po_id = ?", (confirmed, status, po_id))
    n_events = conn.execute("SELECT COUNT(*) FROM supplier_events WHERE po_id = ?", (po_id,)).fetchone()[0]
    payload = {"qty_ordered": requested, "qty_confirmed": confirmed, "message": message}
    conn.execute("INSERT INTO supplier_events VALUES (?, ?, ?, ?, ?, ?)",
                 (f"EVT-{po_id}-{n_events + 1}", po_id, po["supplier_id"], EVENT_TYPES[status],
                  json.dumps(payload), day(0)))
    audit(conn, current_run_id(conn), ACTOR, "PO_" + status, po_id, payload)
    return SupplierResponse(po_id, requested, confirmed, status, message)


def release(conn: sqlite3.Connection, po_id: str) -> None:
    """A cancelled PO gives its confirmed units back to the supplier's availability."""
    po = conn.execute("SELECT supplier_id, sku, qty_confirmed FROM purchase_orders WHERE po_id = ?", (po_id,)).fetchone()
    units = (po["qty_confirmed"] or 0) if po else 0
    if units:
        conn.execute("UPDATE supplier_live_availability SET available_units = available_units + ? "
                     "WHERE supplier_id = ? AND sku = ?", (units, po["supplier_id"], po["sku"]))
        audit(conn, current_run_id(conn), ACTOR, "UNITS_RELEASED", po_id, {"units": units})
