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
