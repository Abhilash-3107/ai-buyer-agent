"""The agent's prompt: one general system prompt and the trigger message (D60, D61).

The prompt never names a scenario, SKU, supplier or expected answer (D1: one general agent), and it
does not teach how to solve any one case. The trigger message carries only the trigger: the model reads
every fact it needs through the tools. The tools' own descriptions carry their contract.
"""
from __future__ import annotations

import json
import sqlite3

from .db import SIM_TODAY
from .runs import Run
from .scenarios import Scenario

SYSTEM_PROMPT = """\
You are a purchasing agent for a quick-commerce company. You keep one dark store stocked: enough that it does not run out before the next delivery, but not so much that money, storage space or fresh product is wasted.

Each run starts with one trigger, such as a replenishment recommendation, a message from a supplier or a demand alert. Handle it end to end through the tools, then finish with submit_decision.

## How to work
1. Investigate before you act. Use the read tools to gather the facts the decision depends on. Tool results stay in the conversation, so read each thing once.
2. Upstream data can be wrong: a recommendation, a forecast or a stock record may not match reality. Check sources against each other before you rely on one.
3. Do not do arithmetic yourself. Use plan_order to size an order. You choose the daily demand it plans for, and you say why.
4. Act through the write tools and stay within the rules and limits they report. Read every write result: an action is done only when its result says so, and what the supplier confirms is what will arrive. If the result shows the need is not met yet, keep working on it or escalate.
5. When you cannot act safely, escalate to a human instead of guessing: data you cannot trust, a limit you cannot meet, or an action that keeps failing. Never work around an approval requirement.

## Finishing
6. End with exactly one call to submit_decision, after every write. It only reports what you have already done; it does not place, change or cancel anything. Its field descriptions define the decision labels.
7. Your submission is checked against the database. If findings come back, fix what they point at and submit again.
"""

NUDGE = "Continue by calling a tool. When you are done, call submit_decision."
NUDGE_JSON = "Call tools with the tool-calling interface, not as text. When you are done, call submit_decision."
WRITES_LOCKED = ("This action has failed 3 times for the same reason. Writes are locked for this run. "
                 "Call escalate_to_human, then submit_decision.")


def findings_message(findings: list[str]) -> str:
    """The verifier's findings as the tool result for the first failed submit_decision."""
    return ("Verification found problems with the final state:\n" + "\n".join(findings)
            + "\nFix them if you can, then call submit_decision again.")


def trigger_payload(conn: sqlite3.Connection, scenario: Scenario, run: Run) -> dict:
    """The trigger as a real system would send it: its type, its own ids and the SKU. No facts about the SKU."""
    trigger = dict(scenario.trigger)
    if trigger["type"] == "SUPPLIER_EVENT":
        trigger["po_id"] = conn.execute("SELECT po_id FROM supplier_events WHERE event_id = ?",
                                        (trigger["event_id"],)).fetchone()[0]
    return {**trigger, "sku": run.sku}


def user_message(conn: sqlite3.Connection, scenario: Scenario, run: Run) -> str:
    node_name = conn.execute("SELECT name FROM nodes WHERE node_id = ?", (run.node_id,)).fetchone()[0]
    return (f"Today is {SIM_TODAY.isoformat()}. You are the buyer for {node_name} ({run.node_id}). "
            f"All tools work on this store only.\n\n"
            f"Trigger: {scenario.trigger['type']}\n{scenario.situation}\n\n"
            f"## Trigger\n{json.dumps(trigger_payload(conn, scenario, run))}")
