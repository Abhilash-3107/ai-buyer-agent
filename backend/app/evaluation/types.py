"""Evaluation types: the check names, one check and the score card of a run."""
from __future__ import annotations

from dataclasses import dataclass

CHECK_NAMES = ("decision", "information", "constraints", "action", "validation", "recovery")


@dataclass(frozen=True)
class Check:
    name: str  # one of CHECK_NAMES
    applicable: bool
    passed: bool
    reason: str  # human-readable, with the numbers


@dataclass(frozen=True)
class ScoreCard:
    scenario_id: str
    run_id: str
    model: str
    checks: tuple[Check, ...]
    passed: bool  # every applicable check passed
    outcome: str  # DECIDED | MAX_STEPS | LLM_ERROR | CONTEXT_TRUNCATED
    decision: str | None
    new_buy_units: int
    turns: int
    tool_calls: int  # every call the model made
    blocked_writes: int
    tokens_in: int
    tokens_out: int
    latency_s: float
    verifier_findings: tuple[str, ...]
    info_read: tuple[str, ...]  # every information category the agent read
    repeat_reads: int  # read calls that repeated an earlier successful read with the same arguments
