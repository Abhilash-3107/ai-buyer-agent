"""Scenario types: the expected outcome, the scenario record and the decision vocabulary."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from enum import StrEnum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .builder import Builder

# Information categories an agent can look at (the allowed values for `Expected.required_info`).
INFO_CATEGORIES = frozenset({
    "inventory", "sales_history", "forecast", "promotions", "open_pos",
    "suppliers", "budget", "storage", "supplier_events",
})

# Decision vocabulary - what the agent concludes about the plan/recommendation it was given.
class Decision(StrEnum):
    ACCEPT = "ACCEPT"
    MODIFY = "MODIFY"
    REJECT = "REJECT"
    INVESTIGATE = "INVESTIGATE"


ACCEPT, MODIFY, REJECT, INVESTIGATE = Decision.ACCEPT, Decision.MODIFY, Decision.REJECT, Decision.INVESTIGATE


@dataclass(frozen=True)
class Expected:
    decision: Decision
    # Units expected to arrive (confirmed qty if the supplier responded, else ordered qty) on POs the
    # agent created or increased, measured in the final DB state. (0, 0) means "must not buy anything".
    new_buy_qty: tuple[int, int]
    # Information categories the agent MUST look at before deciding (checked against its tool calls).
    required_info: tuple[str, ...] = ()
    # If the agent buys, only these suppliers are acceptable.
    allowed_suppliers: tuple[str, ...] | None = None
    # Escalation kind the agent must raise to a human (None = not required).
    escalation: str | None = None
    # Hand-worked numbers, shown in the UI and eval report.
    worked_example: str = ""


@dataclass(frozen=True)
class Scenario:
    id: str
    group: int                 # which assignment scenario (1-4)
    title: str
    situation: str             # what the buyer/agent is told - the trigger
    summary: str               # plain description of the case, shown in the UI only (never in the prompt)
    trigger: dict
    expected: Expected
    build: Callable[[Builder], None] = field(repr=False)
