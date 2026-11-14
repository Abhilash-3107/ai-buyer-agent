"""The agent package's data types: the final answer, the run record, trace events and verifier findings."""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel, ConfigDict, Field

if TYPE_CHECKING:
    from ..purchasing.types import Run
    from .tools import ToolCallRecord


class RunOutcome(StrEnum):
    DECIDED = "DECIDED"
    MAX_STEPS = "MAX_STEPS"
    LLM_ERROR = "LLM_ERROR"
    CONTEXT_TRUNCATED = "CONTEXT_TRUNCATED"
    INTERRUPTED = "INTERRUPTED"  # API only: the server stopped before the run finished


class SubmitDecisionArgs(BaseModel):
    """The agent's structured final answer; the verifier checks it against the database."""
    model_config = ConfigDict(extra="forbid")
    # Literal, not the Decision enum: an Enum puts $defs/$ref in the schema the model sees (test_enums keeps them equal)
    decision: Literal["ACCEPT", "MODIFY", "REJECT", "INVESTIGATE"] = Field(description=(
        "ACCEPT: what the trigger proposes (a recommended order, a supplier's changed confirmation) or, if it "
        "proposes nothing, the current plan stands as it is; you carried it out if it needed carrying out. "
        "MODIFY: you changed purchasing beyond what the trigger proposed: you created, resized or cancelled a PO. "
        "REJECT: the proposal should not be carried out, and you bought nothing. "
        "INVESTIGATE: the data cannot support a decision; you escalated it for investigation and bought nothing."))
    new_units: int = Field(ge=0, description=(
        "Units that will ARRIVE from POs you created or increased, using the supplier's confirmed quantity, "
        "not what you asked for. 0 if none."))
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
class TraceEvent:
    seq: int
    turn: int  # 0 = before the first model call
    type: str  # run_started | llm_request | llm_response | tool_call | tool_result | harness_step | nudge
    #            | recovered_tool_call | budget_locked | decision | verification | flagged | run_finished | error
    #            llm_request: the messages added since the previous request (+ the tool list on the first one).
    #            harness_step: a step the code ran for one agent tool call: its request check (stage "request":
    #            ACCEPTED, REJECTED or LOCKED), then for a write the validator, approval and supplier.
    data: dict  # JSON-safe
    ts: float  # seconds since run start


@dataclass(frozen=True)
class Finding:
    code: str
    message: str
    details: dict


@dataclass(frozen=True)
class VerificationResult:
    passed: bool
    findings: tuple[Finding, ...]


@dataclass(frozen=True)
class AgentResult:
    run: Run
    outcome: RunOutcome
    decision: SubmitDecisionArgs | None
    verification: VerificationResult
    steps: int
    tokens_in: int
    tokens_out: int
    latency_s: float
    trace_path: Path | None
    conn: sqlite3.Connection  # the run's database, for the caller to inspect
    tool_calls: tuple[ToolCallRecord, ...]  # every tool call the model made
