"""Loop 3: independent checks on the final database state (D32).

The verifier trusts the database, not the model's story: it re-derives what will arrive,
re-validates every PO the agent touched and looks for an unresolved gap. Findings go back to the agent once.
"""
from __future__ import annotations

import json
import sqlite3

from ..purchasing.calculations import (
    demand_stats,
    inbound_arrivals,
    project_stock,
    round_order_qty,
)
from ..purchasing.context import load_sku_context
from ..purchasing.types import (
    AGENT_ESCALATION_KINDS,
    OPEN_PO_STATUSES,
    PoStatus,
    Run,
    Severity,
    SkuContext,
)
from ..purchasing.validator import validate_purchase
from ..scenarios.types import Decision
from .types import Finding, SubmitDecisionArgs, VerificationResult

OPEN = ", ".join(f"'{s}'" for s in OPEN_PO_STATUSES)
AGENT_KINDS = ", ".join(f"'{k}'" for k in AGENT_ESCALATION_KINDS)


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


def _cancelled(conn: sqlite3.Connection, run: Run) -> bool:
    return conn.execute("SELECT 1 FROM audit_log WHERE run_id = ? AND action = 'PO_CANCELLED'",
                        (run.run_id,)).fetchone() is not None


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


# Escalations that explain a projected stockout: problems buying cannot fix right now (D65). A BUDGET_INCREASE does
# too, but only once the budget is spent (see _budget_left_for_an_order).
STOCKOUT_EXCUSES = ("INVESTIGATION", "SUPPLIER_ISSUE", "OTHER")


def _budget_left_for_an_order(ctx: SkuContext) -> tuple[str, int] | tuple[()]:
    """The cheapest minimum order an approved supplier offers that the remaining budget still pays for, as
    (supplier, units), or () if none fits. A request for more budget explains a gap only once nothing fits:
    asking for more is not a reason to leave the budget you have unspent while the shelf runs empty."""
    fits = [(o.unit_cost * qty, o.supplier_id, qty) for o in ctx.offers if o.is_approved
            for qty in [round_order_qty(1, ctx.case_pack, o.moq)] if o.unit_cost * qty <= ctx.budget_remaining]
    return min(fits)[1:] if fits else ()


def verify(conn: sqlite3.Connection, run: Run, decision: SubmitDecisionArgs | None) -> VerificationResult:
    findings: list[Finding] = []
    touched = touched_pos(conn, run)

    for po in touched:
        demand = recorded_demand(conn, run, po["po_id"])
        if demand is None:
            continue
        ctx = load_sku_context(conn, run.node_id, po["sku"])
        errors = [v for v in validate_purchase(ctx, po["supplier_id"], po["qty_ordered"], demand,
                                               replaces_po_id=po["po_id"]).violations if v.severity == Severity.ERROR]
        if errors:
            findings.append(Finding("PO_INVALID", f"{po['po_id']} no longer passes validation: "
                                    + "; ".join(v.message for v in errors), {"po_id": po["po_id"]}))

    for po in touched:
        if po["status"] != PoStatus.PARTIALLY_CONFIRMED:
            continue
        gap = po["qty_ordered"] - po["qty_confirmed"]
        # A top-up is any open agent PO for the same SKU linked to this one or placed after it: the agent
        # reacted to the short answer. Whether the top-ups were big enough is left to STOCKOUT_UNRESOLVED,
        # so a top-up linked to a different parent does not push the agent into buying the gap twice.
        topped_up = conn.execute(
            f"SELECT 1 FROM purchase_orders WHERE created_by = 'agent' AND status IN ({OPEN}) AND sku = ? "
            "AND node_id = ? AND (parent_po_id = ? OR rowid > (SELECT rowid FROM purchase_orders WHERE po_id = ?))",
            (po["sku"], run.node_id, po["po_id"], po["po_id"])).fetchone()
        if not topped_up and not escalated(conn, run, po_id=po["po_id"]):
            findings.append(Finding(
                "UNRESOLVED_SHORTFALL",
                f"{po['po_id']} was confirmed at {po['qty_confirmed']} of {po['qty_ordered']} units and the gap of "
                f"{gap} is neither covered by a later top-up PO nor escalated.",
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
    if demand > 0 and not any(escalated(conn, run, kind=k) for k in STOCKOUT_EXCUSES):
        primary = next((o for o in ctx.offers if o.is_primary), None)
        horizon = (primary.lead_time_days if primary else 0) + ctx.review_period_days
        stockout = project_stock(ctx.on_hand, demand, inbound_arrivals(ctx)).stockout_day
        unspent = _budget_left_for_an_order(ctx) if escalated(conn, run, kind="BUDGET_INCREASE") else None
        if stockout is not None and stockout < horizon and unspent != ():
            where = f"At {demand:g} units/day the stock runs out on day {stockout}, before the next review (day {horizon})"
            if unspent is None:
                message = f"{where}, and no escalation was raised."
            else:
                supplier_id, qty = unspent
                message = (f"{where}. A BUDGET_INCREASE escalation is open, but it does not explain the gap while "
                           f"${ctx.budget_remaining:,.2f} of the budget is still unspent: enough for a minimum order "
                           f"of {qty} units from {supplier_id}.")
            findings.append(Finding("STOCKOUT_UNRESOLVED", message, {"stockout_day": stockout, "horizon": horizon}))

    if decision.decision == Decision.MODIFY and not touched and not _cancelled(conn, run):
        findings.append(Finding("DECISION_ACTION_MISMATCH",
                                "The decision is MODIFY but no PO was created, resized or cancelled. An escalation "
                                "on its own does not change purchasing, so it is not a MODIFY; the submit_decision "
                                "field description defines each label.",
                                {"decision": decision.decision}))
    if decision.decision in (Decision.REJECT, Decision.INVESTIGATE) and units > 0:
        findings.append(Finding("DECISION_ACTION_MISMATCH",
                                f"The decision is {decision.decision} but {units} new units were bought.",
                                {"decision": decision.decision, "units": units}))
    if decision.decision == Decision.INVESTIGATE and not escalated(conn, run, kind="INVESTIGATION"):
        findings.append(Finding("DECISION_ACTION_MISMATCH",
                                "The decision is INVESTIGATE but no INVESTIGATION escalation was raised.",
                                {"decision": decision.decision}))

    return VerificationResult(not findings, tuple(findings))
