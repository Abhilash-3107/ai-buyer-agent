"""The write pipeline: the ONLY module that writes business tables (D20).

Every PO change goes through the same steps: validate (loop 1), decide who approves, write,
submit to the supplier and return what the supplier actually confirmed (loop 2).
Each action is one transaction and leaves an audit row, including refused attempts.
"""
from __future__ import annotations

import functools
import json
import sqlite3
from dataclasses import asdict, dataclass
from typing import Literal, get_args

from . import supplier_api
from .context import OPEN_PO_STATUSES, SkuContext, load_sku_context
from .db import audit, day
from .policy import approval_for
from .runs import Run
from .supplier_api import SupplierResponse
from .validator import ValidationResult, Violation, validate_purchase

AgentEscalationKind = Literal["INVESTIGATION", "BUDGET_INCREASE", "SUPPLIER_ISSUE", "OTHER"]
AGENT_ESCALATION_KINDS = get_args(AgentEscalationKind)
MODIFIABLE_STATUSES = ("PENDING_APPROVAL", "SUBMITTED")  # D23: never after the supplier has answered

_REFUSAL_AUDIT = {"BLOCKED": "PO_BLOCKED", "NEEDS_JUSTIFICATION": "PO_NEEDS_JUSTIFICATION", "NOT_ALLOWED": "NOT_ALLOWED"}


@dataclass(frozen=True)
class ActionResult:
    ok: bool
    status: str  # WRITTEN | BLOCKED | NEEDS_JUSTIFICATION | PENDING_APPROVAL | NOT_ALLOWED
    po_id: str | None
    violations: tuple[Violation, ...]
    supplier: SupplierResponse | None  # what the supplier actually confirmed (loop 2)
    message: str
    escalation_id: str | None = None  # set when a human queue entry was opened


def _result(status: str, message: str, *, po_id: str | None = None, violations: tuple[Violation, ...] = (),
            supplier: SupplierResponse | None = None, escalation_id: str | None = None) -> ActionResult:
    return ActionResult(status in ("WRITTEN", "PENDING_APPROVAL"), status, po_id, violations, supplier, message,
                        escalation_id)


def _atomic(action):
    """One transaction per action: commit on success, roll back and report on any exception."""
    @functools.wraps(action)
    def wrapper(conn: sqlite3.Connection, *args, **kwargs) -> ActionResult:
        try:
            result = action(conn, *args, **kwargs)
            conn.commit()
            return result
        except Exception as exc:  # noqa: BLE001 - by design every failure rolls back and returns ok=False
            conn.rollback()
            return _result("NOT_ALLOWED", f"{action.__name__} failed and was rolled back: {exc}")
    return wrapper


def _refuse(conn: sqlite3.Connection, run: Run, status: str, attempt: str, entity_id: str | None, message: str,
            violations: tuple[Violation, ...] = (), actor: str = "agent", **details) -> ActionResult:
    audit(conn, run.run_id, actor, _REFUSAL_AUDIT[status], entity_id,
          {"attempt": attempt, "message": message, "violations": [asdict(v) for v in violations], **details})
    return _result(status, message, po_id=entity_id, violations=violations)


def _next_id(conn: sqlite3.Connection, table: str, column: str, prefix: str) -> str:
    """Counter derived from the rows already in this run's DB, so ids are stable across repeats."""
    n = conn.execute(f"SELECT COUNT(*) FROM {table} WHERE {column} LIKE ?", (prefix + "%",)).fetchone()[0]
    return f"{prefix}{n + 1:03d}"


def _own_po(conn: sqlite3.Connection, run: Run, po_id: str) -> sqlite3.Row | None:
    """A PO of another node looks exactly like a missing one, so a run cannot probe other nodes."""
    return conn.execute("SELECT * FROM purchase_orders WHERE po_id = ? AND node_id = ?", (po_id, run.node_id)).fetchone()


def _append_note(old: str | None, text: str) -> str:
    return f"{old} | {text}" if old else text


def _insert_escalation(conn: sqlite3.Connection, run: Run, kind: str, po_id: str | None, summary: str,
                       details: dict) -> str:
    escalation_id = _next_id(conn, "escalations", "escalation_id", "ESC-")
    conn.execute("INSERT INTO escalations (escalation_id, run_id, kind, po_id, summary, details_json, status, created_at) "
                 "VALUES (?, ?, ?, ?, ?, ?, 'OPEN', ?)",
                 (escalation_id, run.run_id, kind, po_id, summary, json.dumps(details, default=str), day(0)))
    return escalation_id


def _close_approval(conn: sqlite3.Connection, po_id: str, status: str) -> None:
    conn.execute("UPDATE escalations SET status = ? WHERE po_id = ? AND kind = 'APPROVAL' AND status = 'OPEN'",
                 (status, po_id))


def _gate(conn: sqlite3.Connection, run: Run, attempt: str, ctx: SkuContext, supplier_id: str, qty: int, daily_demand: float,
          entity_id: str | None, justification: str | None,
          replaces_po_id: str | None = None) -> tuple[ValidationResult, ActionResult | None]:
    """Steps 1-3: errors block, warnings wait for a justification. A refusal is already audited."""
    validation = validate_purchase(ctx, supplier_id, qty, daily_demand, replaces_po_id=replaces_po_id)
    errors = [v for v in validation.violations if v.severity == "error"]
    if errors:
        message = "Blocked: " + "; ".join(v.message for v in errors)
        return validation, _refuse(conn, run, "BLOCKED", attempt, entity_id, message, validation.violations,
                                   supplier_id=supplier_id, qty=qty)
    if validation.violations and not (justification or "").strip():
        message = ("Not written: resend with a justification for these warnings: "
                   + "; ".join(v.message for v in validation.violations))
        return validation, _refuse(conn, run, "NEEDS_JUSTIFICATION", attempt, entity_id, message,
                                   validation.violations, supplier_id=supplier_id, qty=qty)
    return validation, None


def _route(conn: sqlite3.Connection, run: Run, po_id: str, po_value: float, audit_action: str,
           details: dict) -> ActionResult:
    """Steps 4-5: a PO over the limit waits for a human (D22), any other goes straight to the supplier."""
    po = conn.execute("SELECT * FROM purchase_orders WHERE po_id = ?", (po_id,)).fetchone()
    decision = approval_for(po_value)
    if not decision.auto_submit:
        conn.execute("UPDATE purchase_orders SET status = 'PENDING_APPROVAL' WHERE po_id = ?", (po_id,))
        summary = f"Approve {po_id}: {po['qty_ordered']} x {po['sku']} for ${po_value:,.2f}"
        approval = {"po_value": po_value, "reason": decision.reason}
        open_row = conn.execute("SELECT escalation_id FROM escalations WHERE po_id = ? AND kind = 'APPROVAL' "
                                "AND status = 'OPEN'", (po_id,)).fetchone()
        if open_row:  # a modified PO keeps its one open approval request
            escalation_id = open_row[0]
            conn.execute("UPDATE escalations SET summary = ?, details_json = ? WHERE escalation_id = ?",
                         (summary, json.dumps(approval), escalation_id))
        else:
            escalation_id = _insert_escalation(conn, run, "APPROVAL", po_id, summary, approval)
        audit(conn, run.run_id, "agent", audit_action, po_id, {**details, "outcome": "PENDING_APPROVAL"})
        return _result("PENDING_APPROVAL", f"{po_id} is held for human approval, the supplier was not contacted: "
                       f"{decision.reason}.", po_id=po_id, escalation_id=escalation_id)

    conn.execute("UPDATE purchase_orders SET status = 'SUBMITTED' WHERE po_id = ?", (po_id,))
    _close_approval(conn, po_id, "WITHDRAWN")
    audit(conn, run.run_id, "agent", audit_action, po_id, {**details, "outcome": "SUBMITTED"})
    response = supplier_api.submit(conn, po_id)
    return _result("WRITTEN", response.message, po_id=po_id, supplier=response)


@_atomic
def create_po(conn: sqlite3.Connection, run: Run, sku: str, supplier_id: str, qty: int, daily_demand: float,
              reason: str, justification: str | None = None, parent_po_id: str | None = None) -> ActionResult:
    try:
        ctx = load_sku_context(conn, run.node_id, sku)
    except KeyError:
        return _refuse(conn, run, "NOT_ALLOWED", "create_po", None, f"{run.node_id} does not stock {sku}", sku=sku)
    if parent_po_id is not None:
        parent = _own_po(conn, run, parent_po_id)
        if parent is None or parent["sku"] != sku:
            return _refuse(conn, run, "NOT_ALLOWED", "create_po", None,
                           f"parent_po_id {parent_po_id} is not a PO for {sku} at {run.node_id}", sku=sku)

    validation, refusal = _gate(conn, run, "create_po", ctx, supplier_id, qty, daily_demand, None, justification)
    if refusal:
        return refusal

    offer = ctx.offer(supplier_id)
    po_id = _next_id(conn, "purchase_orders", "po_id", "PO-A")
    notes = _append_note(reason, f"Justification: {justification.strip()}") if justification else reason
    conn.execute(
        "INSERT INTO purchase_orders (po_id, supplier_id, node_id, sku, qty_ordered, qty_confirmed, unit_cost, status, "
        "expected_arrival, created_at, created_by, parent_po_id, notes) "
        "VALUES (?, ?, ?, ?, ?, NULL, ?, 'PENDING_APPROVAL', ?, ?, 'agent', ?, ?)",
        (po_id, supplier_id, run.node_id, sku, qty, offer.unit_cost, day(offer.lead_time_days), day(0),
         parent_po_id, notes))
    return _route(conn, run, po_id, validation.po_value, "PO_CREATED",
                  {"sku": sku, "supplier_id": supplier_id, "qty": qty, "po_value": validation.po_value,
                   "parent_po_id": parent_po_id, "reason": reason, "justification": justification,
                   "warnings": [v.code for v in validation.violations]})


@_atomic
def modify_po(conn: sqlite3.Connection, run: Run, po_id: str, new_qty: int, daily_demand: float, reason: str,
              justification: str | None = None) -> ActionResult:
    po = _own_po(conn, run, po_id)
    if po is None:
        return _refuse(conn, run, "NOT_ALLOWED", "modify_po", po_id, f"{po_id} is not a PO at {run.node_id}")
    if po["status"] not in MODIFIABLE_STATUSES:
        return _refuse(conn, run, "NOT_ALLOWED", "modify_po", po_id,
                       f"{po_id} is {po['status']}; only {' or '.join(MODIFIABLE_STATUSES)} POs can be modified. "
                       "Add a linked top-up PO or cancel instead.")

    ctx = load_sku_context(conn, run.node_id, po["sku"])
    validation, refusal = _gate(conn, run, "modify_po", ctx, po["supplier_id"], new_qty, daily_demand, po_id,
                                justification, replaces_po_id=po_id)
    if refusal:
        return refusal

    note = f"Modified {po['qty_ordered']} -> {new_qty}: {reason}" + (f" Justification: {justification.strip()}"
                                                                    if justification else "")
    conn.execute("UPDATE purchase_orders SET qty_ordered = ?, qty_confirmed = NULL, unit_cost = ?, notes = ? "
                 "WHERE po_id = ?", (new_qty, ctx.offer(po["supplier_id"]).unit_cost,
                                     _append_note(po["notes"], note), po_id))
    return _route(conn, run, po_id, validation.po_value, "PO_MODIFIED",
                  {"old_qty": po["qty_ordered"], "new_qty": new_qty, "po_value": validation.po_value,
                   "reason": reason, "justification": justification,
                   "warnings": [v.code for v in validation.violations]})


@_atomic
def accept_partial_confirmation(conn: sqlite3.Connection, run: Run, po_id: str, reason: str) -> ActionResult:
    po = _own_po(conn, run, po_id)
    if po is None:
        return _refuse(conn, run, "NOT_ALLOWED", "accept_partial_confirmation", po_id,
                       f"{po_id} is not a PO at {run.node_id}")
    if po["status"] != "PARTIALLY_CONFIRMED":
        return _refuse(conn, run, "NOT_ALLOWED", "accept_partial_confirmation", po_id,
                       f"{po_id} is {po['status']}, not PARTIALLY_CONFIRMED")
    conn.execute("UPDATE purchase_orders SET status = 'CONFIRMED', notes = ? WHERE po_id = ?",
                 (_append_note(po["notes"], f"Accepted partial confirmation: {reason}"), po_id))
    audit(conn, run.run_id, "agent", "PO_PARTIAL_ACCEPTED", po_id,
          {"qty_ordered": po["qty_ordered"], "qty_confirmed": po["qty_confirmed"], "reason": reason})
    return _result("WRITTEN", f"{po_id} is CONFIRMED at the {po['qty_confirmed']} units the supplier can ship "
                   f"(of {po['qty_ordered']} ordered).", po_id=po_id)


@_atomic
def cancel_po(conn: sqlite3.Connection, run: Run, po_id: str, reason: str) -> ActionResult:
    po = _own_po(conn, run, po_id)
    if po is None:
        return _refuse(conn, run, "NOT_ALLOWED", "cancel_po", po_id, f"{po_id} is not a PO at {run.node_id}")
    if po["status"] not in OPEN_PO_STATUSES:
        return _refuse(conn, run, "NOT_ALLOWED", "cancel_po", po_id, f"{po_id} is {po['status']}, not an open PO")
    supplier_api.release(conn, po_id)
    _close_approval(conn, po_id, "WITHDRAWN")
    conn.execute("UPDATE purchase_orders SET status = 'CANCELLED', notes = ? WHERE po_id = ?",
                 (_append_note(po["notes"], f"Cancelled: {reason}"), po_id))
    audit(conn, run.run_id, "agent", "PO_CANCELLED", po_id, {"previous_status": po["status"], "reason": reason})
    return _result("WRITTEN", f"{po_id} is CANCELLED.", po_id=po_id)


@_atomic
def escalate(conn: sqlite3.Connection, run: Run, kind: str, summary: str, details: dict,
             po_id: str | None = None) -> ActionResult:
    """Agent escalations only; APPROVAL entries come from the pipeline, never from the agent."""
    if kind not in AGENT_ESCALATION_KINDS:
        return _refuse(conn, run, "NOT_ALLOWED", "escalate", None,
                       f"Unknown escalation kind {kind!r}; use one of {', '.join(AGENT_ESCALATION_KINDS)}")
    if po_id is not None and _own_po(conn, run, po_id) is None:
        return _refuse(conn, run, "NOT_ALLOWED", "escalate", None, f"{po_id} is not a PO at {run.node_id}")
    escalation_id = _insert_escalation(conn, run, kind, po_id, summary, details)
    audit(conn, run.run_id, "agent", "ESCALATED", escalation_id, {"kind": kind, "po_id": po_id, "summary": summary})
    return _result("WRITTEN", f"Escalation {escalation_id} ({kind}) is open for a human.", po_id=po_id,
                   escalation_id=escalation_id)


def _pending_approval(conn: sqlite3.Connection, run: Run, escalation_id: str,
                      attempt: str) -> tuple[sqlite3.Row | None, ActionResult | None]:
    """The PENDING_APPROVAL PO behind an open APPROVAL escalation, or a refusal."""
    esc = conn.execute("SELECT po_id FROM escalations WHERE escalation_id = ? AND kind = 'APPROVAL' "
                       "AND status = 'OPEN'", (escalation_id,)).fetchone()
    po = _own_po(conn, run, esc["po_id"]) if esc else None
    if po is None or po["status"] != "PENDING_APPROVAL":
        return None, _refuse(conn, run, "NOT_ALLOWED", attempt, None,
                             f"{escalation_id} is not an open approval for a pending PO", actor="human")
    return po, None


@_atomic
def approve_po(conn: sqlite3.Connection, run: Run, escalation_id: str, note: str) -> ActionResult:
    """Human side: release a held PO to the supplier."""
    po, refusal = _pending_approval(conn, run, escalation_id, "approve_po")
    if refusal:
        return refusal
    conn.execute("UPDATE escalations SET status = 'APPROVED' WHERE escalation_id = ?", (escalation_id,))
    conn.execute("UPDATE purchase_orders SET status = 'SUBMITTED', notes = ? WHERE po_id = ?",
                 (_append_note(po["notes"], f"Approved: {note}"), po["po_id"]))
    audit(conn, run.run_id, "human", "PO_APPROVED", po["po_id"], {"escalation_id": escalation_id, "note": note})
    response = supplier_api.submit(conn, po["po_id"])
    return _result("WRITTEN", f"Approved. {response.message}", po_id=po["po_id"], supplier=response,
                   escalation_id=escalation_id)


@_atomic
def reject_po(conn: sqlite3.Connection, run: Run, escalation_id: str, note: str) -> ActionResult:
    """Human side: a held PO never reaches the supplier."""
    po, refusal = _pending_approval(conn, run, escalation_id, "reject_po")
    if refusal:
        return refusal
    conn.execute("UPDATE escalations SET status = 'REJECTED' WHERE escalation_id = ?", (escalation_id,))
    conn.execute("UPDATE purchase_orders SET status = 'CANCELLED', notes = ? WHERE po_id = ?",
                 (_append_note(po["notes"], f"Rejected: {note}"), po["po_id"]))
    audit(conn, run.run_id, "human", "PO_REJECTED", po["po_id"], {"escalation_id": escalation_id, "note": note})
    return _result("WRITTEN", f"{po['po_id']} is CANCELLED, rejected by a human.", po_id=po["po_id"],
                   escalation_id=escalation_id)
