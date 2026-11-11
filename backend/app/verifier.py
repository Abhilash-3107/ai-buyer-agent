"""Loop 3: independent checks on the final database state (D32).

The verifier trusts the database, not the model's story: it re-derives what will arrive,
re-validates every PO the agent touched and looks for an unresolved gap. Findings go back to the agent once.
"""
from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from typing import TYPE_CHECKING

from .actions import AGENT_ESCALATION_KINDS
from .calculations import demand_stats, inbound_arrivals, project_stock
from .context import OPEN_PO_STATUSES, load_sku_context
from .runs import Run
from .validator import validate_purchase

if TYPE_CHECKING:
    from .agent import SubmitDecisionArgs

OPEN = ", ".join(f"'{s}'" for s in OPEN_PO_STATUSES)
AGENT_KINDS = ", ".join(f"'{k}'" for k in AGENT_ESCALATION_KINDS)


@dataclass(frozen=True)
class Finding:
    code: str
    message: str
    details: dict


@dataclass(frozen=True)
class VerificationResult:
    passed: bool
    findings: tuple[Finding, ...]


def _open_agent_pos(conn: sqlite3.Connection, run: Run) -> list[sqlite3.Row]:
    return conn.execute(f"SELECT * FROM purchase_orders WHERE node_id = ? AND created_by = 'agent' "
                        f"AND status IN ({OPEN}) ORDER BY po_id", (run.node_id,)).fetchall()


def _modified(conn: sqlite3.Connection, run: Run) -> dict[str, int]:
    """PO id -> quantity before the agent's first change, for every PO the agent modified."""
    rows = conn.execute("SELECT entity_id, details_json FROM audit_log WHERE run_id = ? AND action = 'PO_MODIFIED' "
                        "ORDER BY id", (run.run_id,)).fetchall()
    first: dict[str, int] = {}
    for r in rows:
        first.setdefault(r["entity_id"], json.loads(r["details_json"])["old_qty"])
    return first


def recorded_demand(conn: sqlite3.Connection, run: Run, po_id: str) -> float | None:
    """The daily demand the agent validated the PO with: its latest create or modify audit row."""
    row = conn.execute("SELECT details_json FROM audit_log WHERE run_id = ? AND entity_id = ? "
                       "AND action IN ('PO_CREATED', 'PO_MODIFIED') ORDER BY id DESC LIMIT 1",
                       (run.run_id, po_id)).fetchone()
    return json.loads(row[0]).get("daily_demand") if row else None


def touched_pos(conn: sqlite3.Connection, run: Run) -> list[sqlite3.Row]:
    """Open POs the agent created or modified."""
    modified = _modified(conn, run)
    return [po for po in conn.execute(f"SELECT * FROM purchase_orders WHERE node_id = ? AND status IN ({OPEN}) "
                                      "ORDER BY po_id", (run.node_id,))
            if po["created_by"] == "agent" or po["po_id"] in modified]


def new_units(conn: sqlite3.Connection, run: Run) -> int:
    """Units expected to arrive on POs the agent created or increased (confirmed quantity where known)."""
    modified = _modified(conn, run)
    total = 0
    for po in touched_pos(conn, run):
        expected = po["qty_ordered"] if po["qty_confirmed"] is None else po["qty_confirmed"]
        total += expected if po["created_by"] == "agent" else max(0, expected - modified[po["po_id"]])
    return total


def escalated(conn: sqlite3.Connection, run: Run, kind: str | None = None, po_id: str | None = None) -> bool:
    """An escalation the agent raised: any kind, or one kind; for a PO, one about it or about nothing in particular."""
    sql = f"SELECT 1 FROM escalations WHERE run_id = ? AND kind IN ({AGENT_KINDS})"
    params: list = [run.run_id]
    if kind:
        sql += " AND kind = ?"
        params.append(kind)
    if po_id:
        sql += " AND (po_id = ? OR po_id IS NULL)"
        params.append(po_id)
    return conn.execute(sql, params).fetchone() is not None


def verify(conn: sqlite3.Connection, run: Run, decision: SubmitDecisionArgs | None) -> VerificationResult:
    findings: list[Finding] = []
    touched = touched_pos(conn, run)

    for po in touched:
        demand = recorded_demand(conn, run, po["po_id"])
        if demand is None:
            continue
        ctx = load_sku_context(conn, run.node_id, po["sku"])
        errors = [v for v in validate_purchase(ctx, po["supplier_id"], po["qty_ordered"], demand,
                                               replaces_po_id=po["po_id"]).violations if v.severity == "error"]
        if errors:
            findings.append(Finding("PO_INVALID", f"{po['po_id']} no longer passes validation: "
                                    + "; ".join(v.message for v in errors), {"po_id": po["po_id"]}))

    for po in touched:
        if po["status"] != "PARTIALLY_CONFIRMED":
            continue
        gap = po["qty_ordered"] - po["qty_confirmed"]
        topped_up = conn.execute(f"SELECT 1 FROM purchase_orders WHERE parent_po_id = ? AND created_by = 'agent' "
                                 f"AND status IN ({OPEN})", (po["po_id"],)).fetchone()
        if not topped_up and not escalated(conn, run, po_id=po["po_id"]):
            findings.append(Finding(
                "UNRESOLVED_SHORTFALL",
                f"{po['po_id']} was confirmed at {po['qty_confirmed']} of {po['qty_ordered']} units and the gap of "
                f"{gap} is neither covered by a top-up PO (parent_po_id={po['po_id']}) nor escalated.",
                {"po_id": po["po_id"], "gap": gap}))

    if decision is None:
        findings.append(Finding("NO_DECISION", "The run ended without a submit_decision call.", {}))
        return VerificationResult(False, tuple(findings))

    units = new_units(conn, run)
    if decision.new_units != units:
        findings.append(Finding(
            "CLAIM_MISMATCH",
            f"submit_decision says new_units={decision.new_units}, but the database expects {units} units to arrive "
            "from the POs you created or increased (the supplier's confirmed quantity where it answered).",
            {"claimed": decision.new_units, "actual": units}))

    ctx = load_sku_context(conn, run.node_id, run.sku)
    demand = decision.daily_demand_used or demand_stats(ctx).forecast_daily  # no stated demand: the forecast mean
    if demand > 0 and not escalated(conn, run):
        primary = next((o for o in ctx.offers if o.is_primary), None)
        horizon = (primary.lead_time_days if primary else 0) + ctx.review_period_days
        stockout = project_stock(ctx.on_hand, demand, inbound_arrivals(ctx)).stockout_day
        if stockout is not None and stockout < horizon:
            findings.append(Finding(
                "STOCKOUT_UNRESOLVED",
                f"At {demand:g} units/day the stock runs out on day {stockout}, before the next review "
                f"(day {horizon}), and no escalation was raised.", {"stockout_day": stockout, "horizon": horizon}))

    if decision.decision in ("REJECT", "INVESTIGATE") and units > 0:
        findings.append(Finding("DECISION_ACTION_MISMATCH",
                                f"The decision is {decision.decision} but {units} new units were bought.",
                                {"decision": decision.decision, "units": units}))
    if decision.decision == "INVESTIGATE" and not escalated(conn, run, kind="INVESTIGATION"):
        findings.append(Finding("DECISION_ACTION_MISMATCH",
                                "The decision is INVESTIGATE but no INVESTIGATION escalation was raised.",
                                {"decision": decision.decision}))

    return VerificationResult(not findings, tuple(findings))
