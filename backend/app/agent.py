"""The agent loop (D29): call the model, run its tools, feed results back, enforce every limit.

The loop owns the limits, not the model: a turn cap, a retry budget for failing writes, a nudge for
text-only replies, a context-truncation guard, and one chance to fix verifier findings. It never raises on model or LLM errors;
whatever happens is recorded in the trace.
"""
from __future__ import annotations

import json
import re
import sqlite3
import time
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from . import actions
from .llm import LLMClient, ToolCall, tool_result_message
from .prompts import (
    NUDGE,
    NUDGE_JSON,
    SNAPSHOT_TOOLS,
    SYSTEM_PROMPT,
    WRITES_LOCKED,
    findings_message,
    user_message,
)
from .runs import Run, new_run
from .scenarios import SCENARIOS
from .tools import TOOLS, ToolCallRecord, ToolSession
from .trace import Trace, TraceEvent
from .verifier import VerificationResult, verify

REQUEST_OK = "Known tool, arguments valid"
RETRY_LIMIT = 3  # the same failure this many times locks writes
# Context windows a local server may silently cut the prompt to (see section 10 of the phase plan).
SUSPICIOUS_INPUT_TOKENS = (2048, 4096, 8192, 16384, 32768, 65536, 131072)


class SubmitDecisionArgs(BaseModel):
    """The agent's structured final answer; the verifier checks it against the database."""
    model_config = ConfigDict(extra="forbid")
    decision: Literal["ACCEPT", "MODIFY", "REJECT", "INVESTIGATE"]
    new_units: int = Field(ge=0, description="Units that will ARRIVE from POs you created or increased (0 if none)")
    daily_demand_used: float | None = Field(description="The daily demand assumption behind the decision")
    key_factors: list[str] = Field(min_length=1, max_length=5, description="Short facts that drove the decision")
    actions_taken: list[str] = Field(description="PO ids and escalation ids, and what happened to each")
    confidence: Literal["low", "medium", "high"]
    summary: str = Field(min_length=1, description="1-3 sentences for the human buyer")


SUBMIT_TOOL = {"type": "function", "function": {
    "name": "submit_decision",
    "description": "Finish the run with your decision. Call it exactly once, after your actions are done.",
    "parameters": SubmitDecisionArgs.model_json_schema()}}


@dataclass(frozen=True)
class AgentResult:
    run: Run
    outcome: str  # DECIDED | MAX_STEPS | LLM_ERROR | CONTEXT_TRUNCATED
    decision: SubmitDecisionArgs | None
    verification: VerificationResult
    steps: int
    tokens_in: int
    tokens_out: int
    latency_s: float
    trace_path: Path | None
    conn: sqlite3.Connection  # the run's database, for the caller to inspect
    tool_calls: tuple[ToolCallRecord, ...]  # every tool call, preloaded or chosen


def _readable(error: ValidationError) -> str:
    return "; ".join(f"{'.'.join(map(str, e['loc'])) or 'arguments'}: {e['msg']}" for e in error.errors())


def _failure_key(name: str, result: dict) -> tuple | None:
    """What makes two failed writes 'the same': tool, status and violation codes (or a supplier shortfall)."""
    if result.get("status") in ("BLOCKED", "NEEDS_JUSTIFICATION", "NOT_ALLOWED"):
        return name, result["status"], tuple(sorted(v["code"] for v in result.get("violations", [])))
    if result.get("shortfall"):
        return name, "SHORTFALL", ()
    return None


def _json_objects(text: str) -> list:
    """The JSON values a text reply holds: each fenced block, or else the whole stripped text."""
    parts = re.findall(r"```(?:json)?\s*(.*?)```", text, re.DOTALL) or [text.strip()]
    found = []
    for part in parts:
        try:
            found.append(json.loads(part))
        except ValueError:
            pass
    return found


def _recover_call(text: str | None, turn: int) -> tuple[ToolCall | None, bool]:
    """Some small models write a tool call as JSON text. Returns the call it holds (if exactly one) and
    whether the text held any JSON at all."""
    found = _json_objects(text or "")
    if len(found) != 1 or not isinstance(found[0], dict):
        return None, bool(found)
    obj = found[0]
    if "decision" in obj and "new_units" in obj:
        name, args = "submit_decision", obj
    else:
        name, args = obj.get("name"), obj.get("arguments")
    if (name not in TOOLS and name != "submit_decision") or not isinstance(args, dict):
        return None, True
    return ToolCall(f"recovered-{turn}", name, args, json.dumps(args)), True


def _preload(session: ToolSession, trace: Trace, scenario_trigger: dict) -> dict:
    """Read what needs no judgement (the trigger's details, the product facts, suppliers, budget and storage) before the first model call."""
    conn, run = session.conn, session.run

    def read(name: str, args: dict) -> dict:
        trace.emit("tool_call", 0, name=name, args=args, by="harness")
        result = session.call(name, args, by="harness")
        trace.emit("tool_result", 0, name=name, ok=result["ok"], result=result, by="harness")
        return result

    kind = scenario_trigger["type"]
    if kind == "RECOMMENDATION_REVIEW":
        details = read("get_recommendation", {"rec_id": scenario_trigger["rec_id"]})
    elif kind == "SUPPLIER_EVENT":
        po_id = conn.execute("SELECT po_id FROM supplier_events WHERE event_id = ?",
                             (scenario_trigger["event_id"],)).fetchone()[0]
        details = read("get_supplier_events", {"po_id": po_id})
    else:
        details = scenario_trigger
    snapshot = {name: read(name, {"sku": run.sku}) for name in SNAPSHOT_TOOLS}
    node_name = conn.execute("SELECT name FROM nodes WHERE node_id = ?", (run.node_id,)).fetchone()[0]
    return {"node_name": node_name, "trigger_details": details, **snapshot}


def run_agent(scenario_id: str, llm: LLMClient, *, max_turns: int = 30,
              on_event: Callable[[TraceEvent], None] | None = None, in_memory: bool = False) -> AgentResult:
    started = time.perf_counter()
    scenario = SCENARIOS[scenario_id]
    run, conn = new_run(scenario_id, in_memory=in_memory)
    trace_path = None if in_memory else run.path.with_suffix(".trace.jsonl")
    trace = Trace(trace_path, on_event)
    session = ToolSession(conn, run)
    trace.emit("run_started", 0, scenario_id=scenario_id, run_id=run.run_id, node_id=run.node_id, sku=run.sku,
               trigger=scenario.trigger)

    messages = [{"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_message(scenario, run, _preload(session, trace, scenario.trigger))}]
    tools = session.openai_tools() + [SUBMIT_TOOL]

    outcome, decision, verification = "MAX_STEPS", None, VerificationResult(True, ())
    steps = tokens_in = tokens_out = nudges = findings_sent = 0
    sent = 0  # messages already recorded in an llm_request event
    previous_input = None  # the last turn's input_tokens: the conversation only grows
    round_turn = 0  # the turn of the last failed verifier round: one per turn
    failures: Counter = Counter()
    locked = False

    def request_step(call: ToolCall, turn: int, status: str, detail: str) -> None:
        """The harness's check of the model's request, before anything runs."""
        trace.emit("harness_step", turn, call_id=call.id, stage="request", status=status, detail=detail)

    def run_tool(call: ToolCall, turn: int) -> dict:
        nonlocal locked
        if call.parse_error:
            request_step(call, turn, "REJECTED", call.parse_error)
            return {"ok": False, "error": call.parse_error}
        tool = TOOLS.get(call.name)
        is_write = tool is not None and tool.kind == "write"
        if is_write and locked and call.name != "escalate_to_human":
            request_step(call, turn, "LOCKED", WRITES_LOCKED)
            return {"ok": False, "error": WRITES_LOCKED}
        checked = session.check(call.name, call.arguments)
        rejected = isinstance(checked, str)
        request_step(call, turn, "REJECTED" if rejected else "ACCEPTED", checked if rejected else REQUEST_OK)
        result = session.call(call.name, call.arguments, checked=checked)
        for step in result.pop("harness_steps", ()):  # traced as harness steps; the model sees the result without them
            trace.emit("harness_step", turn, call_id=call.id, **step)
        key = _failure_key(call.name, result) if is_write else None
        if key:
            failures[key] += 1
            if failures[key] >= RETRY_LIMIT and not locked:
                locked = True
                trace.emit("budget_locked", turn, key=list(key))
            if locked:
                result = {**result, "writes_locked": WRITES_LOCKED}
        return result

    def emit_verification(turn: int) -> None:
        trace.emit("verification", turn, passed=verification.passed, round=findings_sent + 1,
                   findings=[{"code": f.code, "message": f.message, "details": f.details}
                             for f in verification.findings])

    def submit(call: ToolCall, turn: int) -> tuple[dict, bool]:
        """Returns the tool result and whether the run is over."""
        nonlocal decision, verification, findings_sent, round_turn
        try:
            args = SubmitDecisionArgs.model_validate(call.arguments)
        except ValidationError as e:
            error = f"Invalid arguments for submit_decision: {_readable(e)}"
            request_step(call, turn, "REJECTED", error)
            return {"ok": False, "error": error}, False
        request_step(call, turn, "ACCEPTED", REQUEST_OK)
        decision = args
        trace.emit("decision", turn, **args.model_dump())
        verification = verify(conn, run, decision)
        emit_verification(turn)
        if verification.passed:
            return {"ok": True, "message": "Decision recorded. Verification passed."}, True
        round_turn = turn
        if findings_sent == 0:
            findings_sent = 1
            return {"ok": False, "error": findings_message([f"{f.code}: {f.message}"
                                                            for f in verification.findings])}, False
        return {"ok": False, "error": "Verification still fails. The run is flagged for a human."}, True

    done = False
    for turn in range(1, max_turns + 1):
        steps = turn
        trace.emit("llm_request", turn, messages=messages[sent:], message_count=len(messages),
                   **({"tools": tools} if sent == 0 else {}))  # the tool list never changes, so it is sent once
        sent = len(messages)
        try:
            resp = llm.chat(messages, tools)
        except Exception as exc:  # noqa: BLE001 - a provider failure must end the run cleanly, not crash the caller
            trace.emit("error", turn, message=f"{type(exc).__name__}: {exc}")
            outcome = "LLM_ERROR"
            break
        tokens_in += resp.usage.get("input_tokens", 0)
        tokens_out += resp.usage.get("output_tokens", 0)
        trace.emit("llm_response", turn, text=resp.text, finish_reason=resp.finish_reason, usage=resp.usage,
                   model=resp.model, latency_s=round(resp.latency_s, 3),
                   tool_calls=[{"id": c.id, "name": c.name, "arguments": c.arguments, "parse_error": c.parse_error}
                               for c in resp.tool_calls])

        input_tokens = resp.usage.get("input_tokens")
        if input_tokens is not None:
            truncated = input_tokens in SUSPICIOUS_INPUT_TOKENS or (previous_input or 0) > input_tokens
            previous_input = input_tokens
            if truncated:
                trace.emit("error", turn, message=f"the model server cut the prompt to {input_tokens} tokens; "
                                                  "raise its context window (see ollama/Modelfile.*)")
                outcome = "CONTEXT_TRUNCATED"
                break

        calls, message = resp.tool_calls, resp.message
        if not calls:
            recovered, had_json = _recover_call(resp.text, turn)
            if recovered:
                calls = [recovered]
                message = {**message, "tool_calls": [{"id": recovered.id, "type": "function", "function": {
                    "name": recovered.name, "arguments": recovered.raw_arguments}}]}
                trace.emit("recovered_tool_call", turn, name=recovered.name, args=recovered.arguments,
                           call_id=recovered.id)
            elif not resp.text:
                message = {**message, "content": ""}  # OpenAI rejects null content without tool_calls
        messages.append(message)

        if not calls:
            nudges += 1
            trace.emit("nudge", turn, count=nudges)
            messages.append({"role": "user", "content": NUDGE_JSON if had_json else NUDGE})
            continue

        for call in calls:
            trace.emit("tool_call", turn, name=call.name, args=call.arguments, by="agent", call_id=call.id)
            if done:
                result = {"ok": False, "error": "Ignored: the decision was already submitted."}
            elif call.name == "submit_decision" and not call.parse_error:
                if round_turn == turn:
                    result = {"ok": False, "error": "Ignored: only one submit_decision per turn."}
                else:
                    result, done = submit(call, turn)
            else:
                result = run_tool(call, turn)
            trace.emit("tool_result", turn, name=call.name, ok=result.get("ok"), result=result, by="agent",
                       call_id=call.id)
            messages.append(tool_result_message(call.id, result))
        if done:
            outcome = "DECIDED"
            break

    if outcome != "DECIDED":
        decision = None  # a submission the verifier already rejected must not be re-checked and pass
        verification = verify(conn, run, None)
        emit_verification(steps)
    if not verification.passed:
        flag = actions.flag_run(conn, run, "The run ended with verification findings nobody resolved.",
                                {"outcome": outcome, "findings": [f"{f.code}: {f.message}"
                                                                  for f in verification.findings]})
        trace.emit("flagged", steps, escalation_id=flag.escalation_id, message=flag.message,
                   findings=[f"{f.code}: {f.message}" for f in verification.findings])

    latency = round(time.perf_counter() - started, 3)
    trace.emit("run_finished", steps, outcome=outcome, steps=steps, tokens_in=tokens_in, tokens_out=tokens_out,
               latency_s=latency, verification_passed=verification.passed)
    return AgentResult(run, outcome, decision, verification, steps, tokens_in, tokens_out, latency,
                       trace_path, conn, tuple(session.calls))
