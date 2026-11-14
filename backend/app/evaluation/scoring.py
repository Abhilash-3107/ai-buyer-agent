"""Phase 5 scoring: one finished run against its scenario's `Expected`, as the six questions the assignment asks.

Every check is deterministic and carries a human-readable reason. The scorer never calls the LLM:
it reads only the run database, the tool call records and the AgentResult.
"""
from __future__ import annotations

import json

from ..agent.tools import TOOLS, ToolCallRecord, ToolKind
from ..agent.types import AgentResult, RunOutcome
from ..agent.verifier import escalated, new_units, recorded_demand, touched_pos
from ..purchasing.context import load_sku_context
from ..purchasing.types import ActionStatus, Severity
from ..purchasing.validator import validate_purchase
from ..scenarios.types import Scenario
from .types import Check, ScoreCard

REFUSED = (ActionStatus.BLOCKED, ActionStatus.NEEDS_JUSTIFICATION)  # write statuses that mean "the first action did not work"


def _band(lo: int, hi: int) -> str:
    return str(lo) if lo == hi else f"{lo}-{hi}"


def _decision(scenario: Scenario, result: AgentResult) -> Check:
    want, got = scenario.expected.decision, result.decision.decision if result.decision else None
    if got is None:
        return Check("decision", True, False, f"no decision was submitted (run ended {result.outcome}), expected {want}")
    return Check("decision", True, got == want, f"decided {got}, expected {want}")


def _information(scenario: Scenario, result: AgentResult) -> tuple[Check, tuple[str, ...]]:
    required = set(scenario.expected.required_info)
    read = {r.category for r in result.tool_calls if r.ok and r.category}
    missing = sorted(required - read)
    if missing:
        return Check("information", True, False, f"never read: {', '.join(missing)}"), tuple(sorted(read))
    return Check("information", True, True, f"all {len(required)} required categories read"), tuple(sorted(read))


def _repeat_reads(calls: tuple[ToolCallRecord, ...]) -> int:
    """Reads the model had already done: same tool, same arguments, after a successful one."""
    seen, repeats = set(), 0
    for r in calls:
        if r.name not in TOOLS or TOOLS[r.name].kind != ToolKind.READ:
            continue
        key = (r.name, json.dumps(r.args, sort_keys=True))
        repeats += key in seen
        if r.ok:
            seen.add(key)
    return repeats


def _constraints(result: AgentResult) -> Check:
    problems = []
    for po in touched_pos(result.conn, result.run):
        ctx = load_sku_context(result.conn, result.run.node_id, po["sku"])
        offer = ctx.offer(po["supplier_id"])
        if offer is None:
            problems.append(f"{po['po_id']} went to {po['supplier_id']}, which does not offer {po['sku']} at all")
        elif not offer.is_approved:
            problems.append(f"{po['po_id']} went to {po['supplier_id']}, which is not an approved supplier")
        demand = recorded_demand(result.conn, result.run, po["po_id"])
        if demand is None:
            continue
        validation = validate_purchase(ctx, po["supplier_id"], po["qty_ordered"], demand, replaces_po_id=po["po_id"])
        problems += [f"{po['po_id']}: {v.message}" for v in validation.violations
                     if v.severity == Severity.ERROR and v.code != "SUPPLIER_NOT_APPROVED"]  # reported above, demand-free
    if problems:
        return Check("constraints", True, False, "; ".join(problems))
    return Check("constraints", True, True, "every PO the agent created or changed passes validation at its recorded demand")


def _action(scenario: Scenario, result: AgentResult, units: int) -> Check:
    exp, problems = scenario.expected, []
    if result.outcome != RunOutcome.DECIDED:
        return Check("action", True, False, f"run did not finish ({result.outcome})")
    lo, hi = exp.new_buy_qty
    if not lo <= units <= hi:
        problems.append(f"{units} units, expected {_band(lo, hi)}")
    if exp.allowed_suppliers is not None:
        used = sorted({po["supplier_id"] for po in touched_pos(result.conn, result.run)})
        if not set(used) <= set(exp.allowed_suppliers):
            problems.append(f"used {', '.join(used)}, allowed {', '.join(exp.allowed_suppliers)}")
    if exp.escalation and not escalated(result.conn, result.run, kind=exp.escalation):
        problems.append(f"no {exp.escalation} escalation was raised")
    if problems:
        return Check("action", True, False, "; ".join(problems))
    return Check("action", True, True, f"{units} units, expected {_band(lo, hi)}"
                 + (f"; {exp.escalation} escalation raised" if exp.escalation else ""))


def _validation(result: AgentResult) -> Check:
    if result.outcome != RunOutcome.DECIDED:
        return Check("validation", True, False, f"the run ended {result.outcome} without submit_decision")
    if not result.verification.passed:
        return Check("validation", True, False, "verifier findings: " + "; ".join(f.code for f in result.verification.findings))
    return Check("validation", True, True, "submit_decision was verified against the database with no findings")


def _failed(record: ToolCallRecord) -> bool:
    return record.result.get("status") in REFUSED or bool(record.result.get("shortfall"))


def _is_write(record: ToolCallRecord) -> bool:
    return record.name in TOOLS and TOOLS[record.name].kind == ToolKind.WRITE


def _recovery(result: AgentResult, action_passed: bool) -> Check:
    """A failure is recovered by a later successful write or escalation, or by rightly giving up: the run
    ended DECIDED and the action check passed (for example a refused PO followed by a correct REJECT)."""
    writes = [r for r in result.tool_calls if _is_write(r)]
    failures = [i for i, r in enumerate(writes) if _failed(r)]
    if not failures:
        return Check("recovery", False, True, "no write failed, nothing to recover from")
    abandoned = result.outcome == RunOutcome.DECIDED and action_passed
    unrecovered = [] if abandoned else [writes[i] for i in failures if not any(
        w.ok and not _failed(w) and (w.name == "escalate_to_human" or w.result.get("status") in (ActionStatus.WRITTEN, ActionStatus.PENDING_APPROVAL))
        for w in writes[i + 1:])]
    if unrecovered:
        return Check("recovery", True, False, f"{len(unrecovered)} of {len(failures)} failed writes ("
                     + ", ".join(f"{r.name} {r.result.get('status')}" for r in unrecovered)
                     + ") were never followed by a successful write or an escalation")
    return Check("recovery", True, True, f"all {len(failures)} failed writes were followed by a successful write or an escalation, "
                 "or the agent rightly gave up and the action check passed")


def score_run(scenario: Scenario, result: AgentResult, model: str = "") -> ScoreCard:
    units = new_units(result.conn, result.run)
    information, read = _information(scenario, result)
    action = _action(scenario, result, units)
    checks = (_decision(scenario, result), information, _constraints(result), action,
              _validation(result), _recovery(result, action.passed))
    agent_calls = result.tool_calls
    return ScoreCard(
        scenario_id=scenario.id, run_id=result.run.run_id, model=model, checks=checks,
        passed=all(c.passed for c in checks if c.applicable), outcome=result.outcome,
        decision=result.decision.decision if result.decision else None, new_buy_units=units,
        turns=result.steps, tool_calls=len(agent_calls),
        blocked_writes=sum(1 for r in agent_calls if r.result.get("status") in REFUSED),
        tokens_in=result.tokens_in, tokens_out=result.tokens_out, latency_s=result.latency_s,
        verifier_findings=tuple(f"{f.code}: {f.message}" for f in result.verification.findings),
        info_read=read, repeat_reads=_repeat_reads(agent_calls))
