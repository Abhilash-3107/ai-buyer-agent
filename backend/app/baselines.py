"""Two deliberately dumb policies that prove the eval can tell good behaviour from bad (D38).

Each baseline stands in for the LLM: it answers `run_agent`'s model calls with a fixed plan of tool calls.
So the preload, the write pipeline, the verifier and the trace are exactly the ones the real agent gets,
and `score_run` scores the result unchanged.
"""
from __future__ import annotations

import json
import re
from collections.abc import Callable, Generator

from .llm import LLMResponse, ToolCall

# A policy gets the preloaded prompt and yields one batch of (tool name, arguments) per model turn.
# It receives the previous batch's results back from `yield`.
Batch = list[tuple[str, dict]]
Policy = Callable[[str, dict], Generator[Batch, list[dict], None]]


def _submit(decision: str, units: int, demand: float | None, actions: list[str]) -> tuple[str, dict]:
    return "submit_decision", {
        "decision": decision, "new_units": units, "daily_demand_used": demand,
        "key_factors": ["baseline policy, no analysis"], "actions_taken": actions, "confidence": "high",
        "summary": "A baseline policy acted on the trigger without investigating."}


def _units(result: dict, qty: int) -> int:
    """Units a create_po result will deliver: the supplier's confirmed quantity, else what was ordered."""
    if result.get("supplier"):
        return result["supplier"]["confirmed"]
    return qty if result.get("ok") else 0


def do_nothing(trigger: str, snapshot: dict) -> Generator[Batch, list[dict], None]:
    """Never writes anything, rejects every trigger."""
    while True:
        yield [_submit("REJECT", 0, None, ["did nothing"])]


def rubber_stamp(trigger: str, snapshot: dict) -> Generator[Batch, list[dict], None]:
    """Does what the trigger implies without thinking, and always says ACCEPT."""
    details, mean_7d = snapshot["trigger_details"], snapshot["get_sales_history"]["demand_stats"]["mean_7d"]
    units, demand, note = 0, None, "no purchase"
    if trigger == "SUPPLIER_EVENT":  # the supplier is short: take what it can ship
        yield [("accept_partial_confirmation", {"po_id": details["events"][0]["po_id"],
                                                "reason": "Accepting the supplier's partial confirmation."})]
        note = "accepted the partial confirmation"
    else:
        if trigger == "RECOMMENDATION_REVIEW":  # buy exactly what the engine recommends
            sku, supplier, qty = details["sku"], details["supplier_id"], details["recommended_qty"]
        else:  # DEMAND_ALERT: plan an order at the 7-day mean from the primary supplier
            sku = details["sku"]
            (suppliers,) = yield [("get_suppliers", {"sku": sku})]
            supplier = next(s["supplier_id"] for s in suppliers["suppliers"] if s["is_primary"])
            (plan,) = yield [("plan_order", {"sku": sku, "supplier_id": supplier, "daily_demand": mean_7d})]
            qty = plan.get("suggested_qty", 0)
        demand = mean_7d
        if qty > 0:
            (created,) = yield [("create_po", {
                "sku": sku, "supplier_id": supplier, "qty": qty, "daily_demand": mean_7d,
                "reason": "Following the trigger as given.", "justification": "Following the trigger as given."})]
            units, note = _units(created, qty), f"create_po {qty} from {supplier}: {created.get('status')}"
    while True:
        yield [_submit("ACCEPT", units, demand, [note])]


BASELINES: dict[str, Policy] = {"rubber_stamp": rubber_stamp, "do_nothing": do_nothing}


class BaselineClient:
    """Duck-types LLMClient.chat: replays a policy's batches as model replies."""

    def __init__(self, name: str):
        self.name = name
        self._policy = BASELINES[name]
        self._plan: Generator[Batch, list[dict], None] | None = None
        self._turn = 0

    def chat(self, messages: list[dict], tools: list[dict] | None = None) -> LLMResponse:
        self._turn += 1
        if self._plan is None:
            prompt = messages[1]["content"]
            snapshot = {name: json.loads(body) for name, body in re.findall(r"### (\w+)\n(.*)", prompt)}
            snapshot["trigger_details"] = json.loads(re.search(r"## Trigger details\n(.*)", prompt).group(1))
            self._plan = self._policy(re.search(r"Trigger: (\w+)", prompt).group(1), snapshot)
            batch = next(self._plan)
        else:
            last = []
            for m in reversed(messages):
                if m["role"] != "tool":
                    break
                last.insert(0, json.loads(m["content"]))
            batch = self._plan.send(last)
        calls = [ToolCall(f"baseline-{self._turn}-{i}", name, args, json.dumps(args))
                 for i, (name, args) in enumerate(batch, 1)]
        message = {"role": "assistant", "content": None, "tool_calls": [
            {"id": c.id, "type": "function", "function": {"name": c.name, "arguments": c.raw_arguments}} for c in calls]}
        return LLMResponse(text=None, tool_calls=calls, finish_reason="tool_calls", message=message, model=self.name)
