"""Loop 3 on hand-built final states: each finding fires when it should and stays silent on a correct state."""
from app.agent.runs import new_run
from app.agent.types import SubmitDecisionArgs
from app.agent.verifier import verify
from app.purchasing import actions

M, Q, R = "SUP-METRO", "SUP-QUICK", "SUP-RAPIDO"


def decision(kind="MODIFY", new_units=0, demand=40.0):
    return SubmitDecisionArgs(decision=kind, new_units=new_units, daily_demand_used=demand, key_factors=["f"],
                              actions_taken=["a"], confidence="high", summary="s")


def codes(conn, run, dec):
    return [f.code for f in verify(conn, run, dec).findings]


def s1_with_correct_po():
    run, conn = new_run("S1-MODIFY", in_memory=True)
    assert actions.create_po(conn, run, "SKU-1002", M, 192, 40, "r").ok
    return run, conn


def test_correct_state_passes():
    run, conn = s1_with_correct_po()
    assert verify(conn, run, decision("MODIFY", 192)).passed


def test_no_decision():
    run, conn = new_run("S1-MODIFY", in_memory=True)
    assert codes(conn, run, None) == ["NO_DECISION"]


def test_po_invalid_when_the_final_state_breaks_a_rule():
    run, conn = s1_with_correct_po()
    conn.execute("UPDATE storage_capacity SET occupied_by_other_skus = 1900")  # the shelf filled up since
    assert "PO_INVALID" in codes(conn, run, decision("MODIFY", 192))


def test_claim_mismatch_uses_the_confirmed_quantity():
    run, conn = new_run("S2-ALT-ALSO-SHORT", in_memory=True)
    assert actions.create_po(conn, run, "SKU-2003", Q, 90, 40, "r").supplier.confirmed == 40
    actions.escalate(conn, run, "SUPPLIER_ISSUE", "short", {}, po_id="PO-A001")
    assert codes(conn, run, decision("MODIFY", 90)) == ["CLAIM_MISMATCH"]
    assert verify(conn, run, decision("MODIFY", 40)).passed


def test_unresolved_shortfall_until_topped_up_or_escalated():
    run, conn = new_run("S2-ALT-ALSO-SHORT", in_memory=True)
    actions.create_po(conn, run, "SKU-2003", Q, 90, 40, "r")
    assert "UNRESOLVED_SHORTFALL" in codes(conn, run, decision("MODIFY", 40))

    actions.create_po(conn, run, "SKU-2003", R, 50, 40, "top-up", parent_po_id="PO-A001")
    assert codes(conn, run, decision("MODIFY", 90)) == []

    run, conn = new_run("S2-ALT-ALSO-SHORT", in_memory=True)
    actions.create_po(conn, run, "SKU-2003", Q, 90, 40, "r")
    actions.escalate(conn, run, "SUPPLIER_ISSUE", "no cover", {}, po_id="PO-A001")
    assert codes(conn, run, decision("MODIFY", 40)) == []


def test_a_later_top_up_linked_to_another_parent_still_resolves_the_shortfall():
    """Seen live: the agent topped up QuickSupply's gap but linked it to the original PO. Demanding the exact
    parent link made it buy the gap a second time."""
    run, conn = new_run("S2-ALT-ALSO-SHORT", in_memory=True)
    actions.create_po(conn, run, "SKU-2003", Q, 110, 41, "r", parent_po_id="PO-2003")  # 40 of 110 confirmed
    actions.create_po(conn, run, "SKU-2003", R, 70, 41, "top-up", parent_po_id="PO-2003")
    assert "UNRESOLVED_SHORTFALL" not in codes(conn, run, decision("MODIFY", 110, demand=41.0))


def test_a_po_placed_before_the_short_one_is_not_a_top_up():
    run, conn = new_run("S2-ALT-ALSO-SHORT", in_memory=True)
    actions.create_po(conn, run, "SKU-2003", R, 50, 40, "r")
    actions.create_po(conn, run, "SKU-2003", Q, 90, 40, "r")  # short, and nothing after it
    assert "UNRESOLVED_SHORTFALL" in codes(conn, run, decision("MODIFY", 90))


def test_modify_without_any_po_change_is_a_mismatch():
    """Seen live: the agent only escalated, then relabelled INVESTIGATE as MODIFY to pass."""
    run, conn = new_run("S4-BUDGET", in_memory=True)
    actions.escalate(conn, run, "BUDGET_INCREASE", "need 576, budget fits 396", {})
    assert codes(conn, run, decision("MODIFY", 0, demand=60.0)) == ["DECISION_ACTION_MISMATCH"]
    assert verify(conn, run, decision("REJECT", 0, demand=60.0)).passed


def test_stockout_unresolved_unless_escalated():
    run, conn = new_run("S2-SOURCE-ELSEWHERE", in_memory=True)  # 430 units at 40/day run out on day 10, review on day 13
    assert codes(conn, run, decision("ACCEPT", 0)) == ["STOCKOUT_UNRESOLVED"]
    actions.escalate(conn, run, "SUPPLIER_ISSUE", "no supplier", {})
    assert codes(conn, run, decision("ACCEPT", 0)) == []


def test_stockout_check_falls_back_to_the_forecast_without_a_demand_assumption():
    run, conn = new_run("S2-SOURCE-ELSEWHERE", in_memory=True)
    assert codes(conn, run, decision("ACCEPT", 0, demand=None)) == ["STOCKOUT_UNRESOLVED"]
    actions.escalate(conn, run, "SUPPLIER_ISSUE", "no supplier", {})
    assert codes(conn, run, decision("ACCEPT", 0, demand=None)) == []


def test_reject_or_investigate_with_a_buy_is_a_mismatch():
    run, conn = s1_with_correct_po()
    assert codes(conn, run, decision("REJECT", 192)) == ["DECISION_ACTION_MISMATCH"]
    actions.escalate(conn, run, "INVESTIGATION", "odd data", {})
    assert codes(conn, run, decision("INVESTIGATE", 192)) == ["DECISION_ACTION_MISMATCH"]


def test_investigate_needs_an_investigation_escalation_and_no_buys():
    run, conn = new_run("S1-INVESTIGATE", in_memory=True)
    assert "DECISION_ACTION_MISMATCH" in codes(conn, run, decision("INVESTIGATE", 0))
    actions.escalate(conn, run, "INVESTIGATION", "on-hand 0 contradicts a recent receipt", {})
    assert verify(conn, run, decision("INVESTIGATE", 0)).passed


def test_an_increased_po_counts_only_its_increase():
    run, conn = new_run("S3-SUSTAINED-SPIKE", in_memory=True)  # PO-3001 is a system PO of 300
    assert actions.modify_po(conn, run, "PO-3001", 720, 74, "demand is higher").ok
    assert verify(conn, run, decision("MODIFY", 420, demand=74.0)).passed
    assert codes(conn, run, decision("MODIFY", 720, demand=74.0)) == ["CLAIM_MISMATCH"]
