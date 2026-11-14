"""The prompt is general (D1, D60) and the trigger message carries only the trigger (D61)."""
import json
import re

import pytest
from scripted import scripted_llm

from app.agent import SubmitDecisionArgs, run_agent
from app.prompts import SYSTEM_PROMPT
from app.runs import new_run
from app.scenarios import SCENARIOS
from app.tools import TOOLS


def known_ids() -> set[str]:
    """Every scenario, SKU, supplier and PO id in the data."""
    ids = set(SCENARIOS)
    for sid in SCENARIOS:
        _, conn = new_run(sid, in_memory=True)
        for table, column in (("products", "sku"), ("suppliers", "supplier_id"), ("purchase_orders", "po_id"),
                              ("recommendations", "rec_id"), ("supplier_events", "event_id")):
            ids |= {r[0] for r in conn.execute(f"SELECT {column} FROM {table}")}
    return ids


def trigger_message(sid: str) -> str:
    llm = scripted_llm([RuntimeError("stop after the first call")])
    run_agent(sid, llm, in_memory=True)
    return llm.sent[0][1]["content"]


def test_system_prompt_names_no_scenario_sku_supplier_or_po():
    assert [i for i in known_ids() if i in SYSTEM_PROMPT] == []


@pytest.mark.parametrize("sid", list(SCENARIOS))
def test_trigger_message_holds_only_the_trigger_and_leaks_no_answer(sid):
    message = trigger_message(sid)
    assert sid not in message
    worked = SCENARIOS[sid].expected.worked_example
    assert worked not in message and all(part not in message for part in re.split(r"(?<=\.) ", worked))
    assert SCENARIOS[sid].situation in message

    trigger = json.loads(message.split("## Trigger\n")[1])
    own_id = {"RECOMMENDATION_REVIEW": "rec_id", "SUPPLIER_EVENT": "event_id", "DEMAND_ALERT": "sku"}
    assert trigger["type"] == SCENARIOS[sid].trigger["type"] and trigger[own_id[trigger["type"]]]
    assert trigger["sku"] == re.search(r"SKU-\d+", SCENARIOS[sid].situation).group()
    if trigger["type"] == "SUPPLIER_EVENT":
        assert trigger["po_id"] in SCENARIOS[sid].situation
    assert "### get_" not in message and '"ok": true' not in message  # no tool results: the model reads for itself


@pytest.mark.parametrize("sid", list(SCENARIOS))
def test_run_sku_is_the_triggers_product(sid):
    run, _ = new_run(sid, in_memory=True)
    assert run.sku == re.search(r"SKU-\d+", SCENARIOS[sid].situation).group()


def test_nothing_is_read_before_the_first_model_call():
    events = []
    run_agent("S2-SOURCE-ELSEWHERE", scripted_llm([RuntimeError("stop")]), in_memory=True, on_event=events.append)
    assert [e.type for e in events if e.turn == 0] == ["run_started"]


def test_prompt_teaches_no_tool_strategy():
    """The prompt describes the job and the output contract; when to call which tool is the model's call (D60)."""
    named = [name for name in TOOLS if name in SYSTEM_PROMPT]
    assert named == ["plan_order"]
    assert "submit_decision" in SYSTEM_PROMPT


def test_prompt_has_no_scenario_shaped_advice():
    """A tripwire for rules that solve one scenario group: demand choice, promotions, top-ups, MOQ and budget recipes."""
    banned = ("median", "outlier", "promotion", "shortfall", "parent_po_id", "moq", "budget allows", "forecast when",
              "one-off", "do not fetch")
    assert [w for w in banned if w in SYSTEM_PROMPT.lower()] == []


def test_decision_labels_live_in_the_submit_schema():
    labels = SubmitDecisionArgs.model_json_schema()["properties"]["decision"]["description"]
    assert all(f"{label}:" in labels for label in ("ACCEPT", "MODIFY", "REJECT", "INVESTIGATE"))
    assert "ACCEPT:" not in SYSTEM_PROMPT and "MODIFY:" not in SYSTEM_PROMPT
    assert ("submit_decision only reports what you have already done" not in SYSTEM_PROMPT
            and "It only reports what you have already done; it does not place, change or cancel anything."
            in SYSTEM_PROMPT)


def test_prompt_has_no_dashes_or_vendor_names():
    assert "–" not in SYSTEM_PROMPT and "—" not in SYSTEM_PROMPT
