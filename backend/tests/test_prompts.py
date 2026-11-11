"""The prompt is general (D1) and the trigger message carries the preloaded facts as parseable JSON."""
import json
import re

import pytest
from scripted import scripted_llm

from app.agent import run_agent
from app.prompts import SNAPSHOT_TOOLS, SYSTEM_PROMPT
from app.runs import new_run
from app.scenarios import SCENARIOS


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
def test_trigger_message_has_parseable_blocks_and_leaks_no_answer(sid):
    message = trigger_message(sid)
    assert sid not in message
    worked = SCENARIOS[sid].expected.worked_example
    assert worked not in message and all(part not in message for part in re.split(r"(?<=\.) ", worked))

    details = message.split("## Trigger details\n")[1].split("\n\n## Product snapshot")[0]
    assert json.loads(details)
    snapshot = message.split("## Product snapshot\n")[1]
    for name in SNAPSHOT_TOOLS:
        block = snapshot.split(f"### {name}\n")[1].split("\n")[0]
        assert json.loads(block)["ok"] is True
    assert SCENARIOS[sid].situation in message


@pytest.mark.parametrize("sid", list(SCENARIOS))
def test_run_sku_is_the_triggers_product(sid):
    run, _ = new_run(sid, in_memory=True)
    assert run.sku == re.search(r"SKU-\d+", SCENARIOS[sid].situation).group()


def test_preload_covers_everything_the_agent_always_needs():
    assert SNAPSHOT_TOOLS == ("get_product", "get_inventory", "get_purchase_orders", "get_forecast",
                              "get_sales_history", "get_suppliers", "get_budget", "get_storage")
    # the prompt tells the model not to fetch what the code already did
    assert "supplier offers, budget and storage. Do not fetch those again." in SYSTEM_PROMPT
    assert "Before buying anything, read" not in SYSTEM_PROMPT


def test_prompt_says_submit_decision_writes_nothing_and_defines_modify_broadly():
    assert ("End with exactly one call to submit_decision. submit_decision only reports what you have already done; "
            "it does not place, change or cancel anything. Make every write first, read its result, then submit.") in SYSTEM_PROMPT
    assert ("MODIFY: you changed the plan in any way: you created a PO that differs from what was recommended, "
            "created any PO on a demand alert or supplier message, or changed or cancelled a PO.") in SYSTEM_PROMPT
    assert "Read get_promotions whenever recent sales differ clearly from the forecast." in SYSTEM_PROMPT


def test_prompt_has_no_dashes_or_vendor_names():
    assert "–" not in SYSTEM_PROMPT and "—" not in SYSTEM_PROMPT
