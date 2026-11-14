"""The scorer on scripted runs and hand-built final states: it must pass good behaviour and fail each kind of bad one."""
from dataclasses import replace

from scripted import call, investigate, reply, scripted_llm, submit

from app.agent import run_agent
from app.scenarios import SCENARIOS
from app.scoring import CHECK_NAMES, score_run

S1 = {"sku": "SKU-1002", "supplier_id": "SUP-METRO", "daily_demand": 40, "reason": "r"}
S2 = {"sku": "SKU-2003", "daily_demand": 40, "reason": "r"}
S4 = {"sku": "SKU-4001", "supplier_id": "SUP-METRO", "daily_demand": 60, "reason": "r"}


reads = investigate


def play(scenario_id, script):
    result = run_agent(scenario_id, scripted_llm(script), in_memory=True)
    return result, score_run(SCENARIOS[scenario_id], result)


def check(card, name):
    return next(c for c in card.checks if c.name == name)


def failed(card):
    return sorted(c.name for c in card.checks if c.applicable and not c.passed)


def test_s1_modify_with_a_blocked_800_then_192_passes_everything():
    _, card = play("S1-MODIFY", [reads("SKU-1002"), reply(call("create_po", {**S1, "qty": 800})),
                                 reply(call("create_po", {**S1, "qty": 192})), reply(submit("MODIFY", 192))])
    assert card.passed and card.new_buy_units == 192 and card.blocked_writes == 1
    assert [c.name for c in card.checks] == list(CHECK_NAMES)
    assert check(card, "recovery").applicable and "1 failed writes" in check(card, "recovery").reason
    assert card.info_read == ("budget", "forecast", "inventory", "open_pos", "sales_history", "storage", "suppliers")
    assert card.tool_calls == 10 and card.turns == 4 and card.repeat_reads == 0  # 8 reads + 2 writes


def test_s1_modify_that_only_tried_800_fails_action_and_recovery():
    _, card = play("S1-MODIFY", [reads("SKU-1002"), reply(call("create_po", {**S1, "qty": 800})),
                                 reply(submit("MODIFY", 0)), reply(submit("MODIFY", 0))])
    assert check(card, "action").reason == "0 units, expected 168-240"
    assert {"action", "recovery"} <= set(failed(card)) and not card.passed


def test_a_po_to_an_unapproved_supplier_fails_constraints():
    result, _ = play("S2-SOURCE-ELSEWHERE", [reply(submit("MODIFY", 0))])
    result.conn.execute("INSERT INTO purchase_orders VALUES ('PO-X', 'SUP-SHADY', 'DS-NORTH', 'SKU-2001', 100, NULL, "
                        "6.9, 'SUBMITTED', '2026-11-14', '2026-11-11', 'agent', NULL, NULL)")
    card = score_run(SCENARIOS["S2-SOURCE-ELSEWHERE"], result)
    assert not check(card, "constraints").passed and "SUP-SHADY" in check(card, "constraints").reason
    assert not check(card, "action").passed  # the same PO also fails the supplier allow-list and the band


def test_s2_alt_top_up_after_a_short_confirmation_passes():
    _, card = play("S2-ALT-ALSO-SHORT", [
        reads("SKU-2003"), reply(call("get_supplier_events", {"po_id": "PO-2003"})),
        reply(call("create_po", {**S2, "supplier_id": "SUP-QUICK", "qty": 90})),
        reply(call("create_po", {**S2, "supplier_id": "SUP-RAPIDO", "qty": 50, "parent_po_id": "PO-A001"})),
        reply(submit("MODIFY", 90))])
    assert card.passed and card.new_buy_units == 90
    assert check(card, "recovery").applicable and check(card, "recovery").passed


def test_s2_alt_without_the_top_up_fails_recovery_and_validation():
    _, card = play("S2-ALT-ALSO-SHORT", [
        reads("SKU-2003"), reply(call("create_po", {**S2, "supplier_id": "SUP-QUICK", "qty": 90})),
        reply(submit("MODIFY", 90)), reply(submit("MODIFY", 90))])
    assert {"recovery", "validation"} <= set(failed(card))
    assert "UNRESOLVED_SHORTFALL" in check(card, "validation").reason and card.verifier_findings


def test_s4_budget_pending_approval_with_the_escalation_passes():
    _, card = play("S4-BUDGET", [
        reads("SKU-4001"), reply(call("create_po", {**S4, "qty": 396})),
        reply(call("escalate_to_human", {"kind": "BUDGET_INCREASE", "summary": "need $1,080 more"})),
        reply(submit("MODIFY", 396, demand=60.0))])
    assert card.passed and card.new_buy_units == 396


def test_s4_budget_without_the_escalation_fails_action_naming_it():
    _, card = play("S4-BUDGET", [reads("SKU-4001"), reply(call("create_po", {**S4, "qty": 396})),
                                 reply(submit("MODIFY", 396, demand=60.0)), reply(submit("MODIFY", 396, demand=60.0))])
    assert "no BUDGET_INCREASE escalation was raised" in check(card, "action").reason
    assert not card.passed


def test_do_nothing_passes_a_reject_scenario_and_any_buy_fails_it():
    _, card = play("S1-REJECT", [reads("SKU-1003"), reply(submit("REJECT", 0))])
    assert card.passed and not check(card, "recovery").applicable
    buy = {"sku": "SKU-1003", "supplier_id": "SUP-METRO", "qty": 480, "daily_demand": 20, "reason": "r",
           "justification": "j"}
    _, card = play("S1-REJECT", [reply(call("create_po", buy)), reply(submit("REJECT", 480, demand=20.0))])
    assert not check(card, "action").passed and card.new_buy_units == 480


def test_information_is_missing_when_a_required_category_was_never_read():
    _, card = play("S1-REJECT", [reply(submit("REJECT", 0))])  # nothing is read for the agent any more
    assert check(card, "information").reason == "never read: forecast, inventory, open_pos" and card.info_read == ()
    full, card = play("S1-MODIFY", [reads("SKU-1002"), reply(call("create_po", {**S1, "qty": 192})),
                                    reply(submit("MODIFY", 192))])
    assert check(card, "information").passed
    without_budget = replace(full, tool_calls=tuple(r for r in full.tool_calls if r.category != "budget"))
    card = score_run(SCENARIOS["S1-MODIFY"], without_budget)
    assert not check(card, "information").passed and check(card, "information").reason == "never read: budget"


def test_a_run_that_never_submits_fails_decision_and_validation():
    _, card = play("S1-REJECT", [reply(call("get_budget", {"sku": "SKU-1003"}))] * 30)
    assert card.outcome == "MAX_STEPS" and card.decision is None
    assert {"decision", "validation"} <= set(failed(card))


def test_a_refused_write_then_a_correct_reject_recovers_and_passes():
    s1_reject = {**S1, "sku": "SKU-1003", "daily_demand": 20}
    _, card = play("S1-REJECT", [reads("SKU-1003"), reply(call("create_po", {**s1_reject, "qty": 400})),
                                 reply(submit("REJECT", 0, demand=20.0))])
    assert card.blocked_writes == 1 and card.passed
    assert check(card, "recovery").applicable and check(card, "recovery").passed


def test_an_unfinished_run_fails_action_but_keeps_the_factual_checks():
    result = run_agent("S1-REJECT", scripted_llm([reads("SKU-1003")] * 3), in_memory=True, max_turns=2)
    card = score_run(SCENARIOS["S1-REJECT"], result)
    assert card.outcome == "MAX_STEPS" and not card.passed
    assert check(card, "action").reason == "run did not finish (MAX_STEPS)"
    assert check(card, "information").passed and check(card, "constraints").passed


def test_a_po_to_a_supplier_that_does_not_offer_the_sku_says_so():
    result, _ = play("S2-SOURCE-ELSEWHERE", [reply(submit("MODIFY", 0))])
    result.conn.execute("INSERT INTO purchase_orders VALUES ('PO-X', 'SUP-DAIRY', 'DS-NORTH', 'SKU-2001', 100, NULL, "
                        "6.9, 'SUBMITTED', '2026-11-14', '2026-11-11', 'agent', NULL, NULL)")
    reason = check(score_run(SCENARIOS["S2-SOURCE-ELSEWHERE"], result), "constraints").reason
    assert "SUP-DAIRY" in reason and "does not offer SKU-2001 at all" in reason


def test_repeat_reads_count_the_same_read_done_again():
    _, card = play("S1-REJECT", [reads("SKU-1003"), reads("SKU-1003"),
                                 reply(call("get_sales_history", {"sku": "SKU-1003", "days": 14})),
                                 reply(submit("REJECT", 0))])
    assert card.repeat_reads == 8 and card.passed  # reported, never failed on; other arguments are a new read
