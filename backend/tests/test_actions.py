"""The write pipeline, scenario by scenario."""
from pathlib import Path

import pytest

from app import actions, supplier_api
from app.runs import new_run

M, N = "SUP-METRO", "DS-NORTH"


def scalar(conn, sql, *params):
    return conn.execute(sql, params).fetchone()[0]


def live(conn, supplier, sku):
    return scalar(conn, "SELECT available_units FROM supplier_live_availability WHERE supplier_id = ? AND sku = ?",
                  supplier, sku)


def codes(result):
    return {v.code for v in result.violations}


def test_only_the_supplier_api_reads_live_availability():
    app_dir = Path(actions.__file__).parent
    # builder.py seeds the table; schema.sql defines it. Neither is application logic.
    offenders = [p.name for p in app_dir.glob("*.py")
                 if "supplier_live_availability" in p.read_text() and p.name not in ("supplier_api.py", "builder.py")]
    assert offenders == []


# --- loop 1 ---------------------------------------------------------------------------------------
def test_s1_modify_blocked_then_written():
    run, conn = new_run("S1-MODIFY", in_memory=True)
    pos_before = scalar(conn, "SELECT COUNT(*) FROM purchase_orders")

    blocked = actions.create_po(conn, run, "SKU-1002", M, 800, 40, "engine recommendation")
    assert (blocked.ok, blocked.status, blocked.po_id) == (False, "BLOCKED", None)
    assert "OVER_STORAGE" in codes(blocked) and blocked.supplier is None
    assert scalar(conn, "SELECT COUNT(*) FROM purchase_orders") == pos_before
    assert scalar(conn, "SELECT COUNT(*) FROM audit_log") == 1
    audit = conn.execute("SELECT run_id, actor, action FROM audit_log").fetchone()
    assert tuple(audit) == (run.run_id, "agent", "PO_BLOCKED")

    written = actions.create_po(conn, run, "SKU-1002", M, 192, 40, "order-up-to net of inbound")
    assert (written.ok, written.status, written.po_id) == (True, "WRITTEN", "PO-A001")
    assert (written.supplier.confirmed, written.supplier.status) == (192, "CONFIRMED")
    po = conn.execute("SELECT * FROM purchase_orders WHERE po_id = 'PO-A001'").fetchone()
    assert (po["status"], po["qty_confirmed"], po["created_by"], po["node_id"]) == ("CONFIRMED", 192, "agent", N)
    assert po["expected_arrival"] == "2026-11-16"  # today + Metro's 5-day lead
    assert live(conn, M, "SKU-1002") == 10_000 - 192


def test_ids_are_sequential_within_a_run():
    run, conn = new_run("S1-MODIFY", in_memory=True)
    assert actions.create_po(conn, run, "SKU-1002", M, 120, 40, "r").po_id == "PO-A001"
    second = actions.create_po(conn, run, "SKU-1002", M, 24, 40, "r")
    assert second.status == "BLOCKED"  # below MOQ, so the counter did not move
    assert actions.escalate(conn, run, "OTHER", "x", {}).escalation_id == "ESC-001"
    assert actions.escalate(conn, run, "OTHER", "y", {}).escalation_id == "ESC-002"


def test_unknown_sku_is_not_allowed_and_audited():
    run, conn = new_run("S1-MODIFY", in_memory=True)
    r = actions.create_po(conn, run, "SKU-NOPE", M, 24, 40, "r")
    assert (r.ok, r.status) == (False, "NOT_ALLOWED")
    assert scalar(conn, "SELECT COUNT(*) FROM audit_log WHERE action = 'NOT_ALLOWED'") == 1


# --- warnings need a justification ----------------------------------------------------------------
def test_s2_warnings_are_held_until_justified():
    run, conn = new_run("S2-SOURCE-ELSEWHERE", in_memory=True)
    pos_before = scalar(conn, "SELECT COUNT(*) FROM purchase_orders")
    held = actions.create_po(conn, run, "SKU-2001", "SUP-BULK", 200, 40, "cheapest option")
    assert (held.ok, held.status) == (False, "NEEDS_JUSTIFICATION")
    assert codes(held) == {"LOW_RELIABILITY_SUPPLIER", "ARRIVES_AFTER_STOCKOUT"}
    assert scalar(conn, "SELECT COUNT(*) FROM purchase_orders") == pos_before

    blank = actions.create_po(conn, run, "SKU-2001", "SUP-BULK", 200, 40, "cheapest option", justification="  ")
    assert blank.status == "NEEDS_JUSTIFICATION"

    why = "Alternates cannot cover the gap and a human approved the delay risk"
    done = actions.create_po(conn, run, "SKU-2001", "SUP-BULK", 200, 40, "cheapest option", justification=why)
    assert (done.ok, done.status) == (True, "WRITTEN")
    assert why in scalar(conn, "SELECT notes FROM purchase_orders WHERE po_id = ?", done.po_id)
    created = scalar(conn, "SELECT details_json FROM audit_log WHERE action = 'PO_CREATED'")
    assert why in created and "LOW_RELIABILITY_SUPPLIER" in created


def test_s2_unapproved_supplier_is_blocked_even_with_a_justification():
    run, conn = new_run("S2-SOURCE-ELSEWHERE", in_memory=True)
    r = actions.create_po(conn, run, "SKU-2001", "SUP-SHADY", 50, 40, "cheapest", justification="it is cheap")
    assert r.status == "BLOCKED" and "SUPPLIER_NOT_APPROVED" in codes(r)


# --- loop 2 ---------------------------------------------------------------------------------------
def test_s2_alt_supplier_short_confirms_then_top_up():
    run, conn = new_run("S2-ALT-ALSO-SHORT", in_memory=True)
    quick = actions.create_po(conn, run, "SKU-2003", "SUP-QUICK", 90, 40, "fastest approved supplier")
    assert (quick.ok, quick.status) == (True, "WRITTEN")
    assert (quick.supplier.requested, quick.supplier.confirmed) == (90, 40)
    assert quick.supplier.status == "PARTIALLY_CONFIRMED" and "short by 50" in quick.message
    assert scalar(conn, "SELECT status FROM purchase_orders WHERE po_id = ?", quick.po_id) == "PARTIALLY_CONFIRMED"
    event = conn.execute("SELECT event_type, payload_json FROM supplier_events WHERE po_id = ?",
                         (quick.po_id,)).fetchone()
    assert event["event_type"] == "PARTIAL_CONFIRMATION" and '"qty_confirmed": 40' in event["payload_json"]

    top_up = actions.create_po(conn, run, "SKU-2003", "SUP-RAPIDO", 50, 40, "cover the 50-unit shortfall",
                               parent_po_id=quick.po_id)
    assert (top_up.status, top_up.supplier.confirmed, top_up.supplier.status) == ("WRITTEN", 50, "CONFIRMED")
    assert scalar(conn, "SELECT parent_po_id FROM purchase_orders WHERE po_id = ?", top_up.po_id) == quick.po_id


def test_parent_po_must_be_a_po_for_the_same_sku_at_this_node():
    run, conn = new_run("S2-ALT-ALSO-SHORT", in_memory=True)
    r = actions.create_po(conn, run, "SKU-2003", "SUP-RAPIDO", 50, 40, "top up", parent_po_id="PO-NOPE")
    assert r.status == "NOT_ALLOWED"


def test_s2_accept_short():
    run, conn = new_run("S2-ACCEPT-SHORT", in_memory=True)
    r = actions.accept_partial_confirmation(conn, run, "PO-2002", "stock already covers demand")
    assert (r.ok, r.status) == (True, "WRITTEN")
    po = conn.execute("SELECT status, qty_confirmed FROM purchase_orders WHERE po_id = 'PO-2002'").fetchone()
    assert (po["status"], po["qty_confirmed"]) == ("CONFIRMED", 250)
    again = actions.accept_partial_confirmation(conn, run, "PO-2002", "again")
    assert again.status == "NOT_ALLOWED"


# --- modify ---------------------------------------------------------------------------------------
def test_s3_modify_keeps_the_arrival_date_and_resubmits():
    run, conn = new_run("S3-SUSTAINED-SPIKE", in_memory=True)
    arrival = scalar(conn, "SELECT expected_arrival FROM purchase_orders WHERE po_id = 'PO-3001'")
    r = actions.modify_po(conn, run, "PO-3001", 720, 74.3, "sustained demand, not a spike")
    assert (r.ok, r.status, r.po_id) == (True, "WRITTEN", "PO-3001")
    assert r.supplier.confirmed == 720
    po = conn.execute("SELECT * FROM purchase_orders WHERE po_id = 'PO-3001'").fetchone()
    assert (po["qty_ordered"], po["qty_confirmed"], po["status"]) == (720, 720, "CONFIRMED")
    assert po["expected_arrival"] == arrival
    assert scalar(conn, "SELECT COUNT(*) FROM audit_log WHERE action = 'PO_MODIFIED'") == 1

    again = actions.modify_po(conn, run, "PO-3001", 600, 74.3, "second change")
    assert (again.ok, again.status) == (False, "NOT_ALLOWED")  # CONFIRMED is final (D23)
    assert scalar(conn, "SELECT qty_ordered FROM purchase_orders WHERE po_id = 'PO-3001'") == 720


def test_modify_is_validated_like_a_new_po():
    run, conn = new_run("S3-SUSTAINED-SPIKE", in_memory=True)
    r = actions.modify_po(conn, run, "PO-3001", 100_000, 74.3, "too big")
    assert r.status == "BLOCKED" and "OVER_STORAGE" in codes(r)
    assert scalar(conn, "SELECT qty_ordered FROM purchase_orders WHERE po_id = 'PO-3001'") == 300


def test_modify_confirmed_po_not_allowed():
    run, conn = new_run("S1-MODIFY", in_memory=True)
    r = actions.modify_po(conn, run, "PO-1101", 100, 40, "r")
    assert r.status == "NOT_ALLOWED" and "CONFIRMED" in r.message


# --- approval -------------------------------------------------------------------------------------
def test_s4_over_the_limit_waits_for_a_human_then_approve():
    run, conn = new_run("S4-BUDGET", in_memory=True)
    r = actions.create_po(conn, run, "SKU-4001", M, 396, 60, "fits the remaining budget")
    assert (r.ok, r.status, r.supplier) == (True, "PENDING_APPROVAL", None)
    assert scalar(conn, "SELECT status FROM purchase_orders WHERE po_id = ?", r.po_id) == "PENDING_APPROVAL"
    esc = conn.execute("SELECT * FROM escalations WHERE escalation_id = ?", (r.escalation_id,)).fetchone()
    assert (esc["kind"], esc["status"], esc["po_id"]) == ("APPROVAL", "OPEN", r.po_id)
    assert scalar(conn, "SELECT COUNT(*) FROM supplier_events") == 0  # the supplier was not contacted
    assert live(conn, M, "SKU-4001") == 10_000

    approved = actions.approve_po(conn, run, r.escalation_id, "ok to buy")
    assert (approved.ok, approved.status, approved.supplier.confirmed) == (True, "WRITTEN", 396)
    assert scalar(conn, "SELECT status FROM purchase_orders WHERE po_id = ?", r.po_id) == "CONFIRMED"
    assert scalar(conn, "SELECT status FROM escalations WHERE escalation_id = ?", r.escalation_id) == "APPROVED"
    assert actions.approve_po(conn, run, r.escalation_id, "twice").status == "NOT_ALLOWED"


def test_s4_reject_cancels_the_pending_po():
    run, conn = new_run("S4-BUDGET", in_memory=True)
    r = actions.create_po(conn, run, "SKU-4001", M, 396, 60, "fits the remaining budget")
    rejected = actions.reject_po(conn, run, r.escalation_id, "too much")
    assert (rejected.ok, rejected.status) == (True, "WRITTEN")
    assert scalar(conn, "SELECT status FROM purchase_orders WHERE po_id = ?", r.po_id) == "CANCELLED"
    assert scalar(conn, "SELECT status FROM escalations WHERE escalation_id = ?", r.escalation_id) == "REJECTED"
    assert scalar(conn, "SELECT COUNT(*) FROM supplier_events") == 0
    assert live(conn, M, "SKU-4001") == 10_000


def test_modifying_a_pending_po_keeps_one_open_approval_and_withdraws_it_when_no_longer_needed():
    run, conn = new_run("S4-BUDGET", in_memory=True)
    r = actions.create_po(conn, run, "SKU-4001", M, 396, 60, "fits the remaining budget")
    smaller = actions.modify_po(conn, run, r.po_id, 360, 60, "trim")
    assert smaller.status == "PENDING_APPROVAL" and smaller.escalation_id == r.escalation_id
    assert scalar(conn, "SELECT COUNT(*) FROM escalations WHERE kind = 'APPROVAL'") == 1
    small = actions.modify_po(conn, run, r.po_id, 120, 60, "trim more")  # $720, under the limit
    assert (small.status, small.supplier.confirmed) == ("WRITTEN", 120)
    assert scalar(conn, "SELECT status FROM escalations WHERE escalation_id = ?", r.escalation_id) == "WITHDRAWN"


def test_cancel_pending_po_withdraws_its_approval():
    run, conn = new_run("S4-BUDGET", in_memory=True)
    r = actions.create_po(conn, run, "SKU-4001", M, 396, 60, "fits the remaining budget")
    assert actions.cancel_po(conn, run, r.po_id, "changed my mind").status == "WRITTEN"
    assert scalar(conn, "SELECT status FROM escalations WHERE escalation_id = ?", r.escalation_id) == "WITHDRAWN"
    assert actions.approve_po(conn, run, r.escalation_id, "late").status == "NOT_ALLOWED"


def test_s4_escalate_budget_increase():
    run, conn = new_run("S4-BUDGET", in_memory=True)
    r = actions.escalate(conn, run, "BUDGET_INCREASE", "Need $1,080 more for 180 units", {"amount": 1080})
    assert (r.ok, r.status) == (True, "WRITTEN")
    esc = conn.execute("SELECT * FROM escalations WHERE escalation_id = ?", (r.escalation_id,)).fetchone()
    assert (esc["kind"], esc["status"], esc["run_id"]) == ("BUDGET_INCREASE", "OPEN", run.run_id)
    assert '"amount": 1080' in esc["details_json"]


def test_agent_cannot_open_an_approval_escalation_or_use_an_unknown_kind():
    run, conn = new_run("S4-BUDGET", in_memory=True)
    for kind in ("APPROVAL", "NONSENSE"):
        assert actions.escalate(conn, run, kind, "x", {}).status == "NOT_ALLOWED"
    assert scalar(conn, "SELECT COUNT(*) FROM escalations") == 0


# --- S4-MOQ ---------------------------------------------------------------------------------------
def test_s4_moq_dairy_blocked_farmfresh_confirmed():
    run, conn = new_run("S4-MOQ-VS-SHELF-LIFE", in_memory=True)
    dairy = actions.create_po(conn, run, "SKU-4002", "SUP-DAIRY", 180, 12, "recommendation")
    assert dairy.status == "BLOCKED" and "OVER_SHELF_LIFE" in codes(dairy)
    farm = actions.create_po(conn, run, "SKU-4002", "SUP-FARM", 42, 12, "smaller MOQ")
    assert (farm.status, farm.supplier.confirmed) == ("WRITTEN", 42)


# --- cancel ---------------------------------------------------------------------------------------
def test_cancel_returns_units_to_live_availability():
    run, conn = new_run("S1-MODIFY", in_memory=True)
    r = actions.create_po(conn, run, "SKU-1002", M, 192, 40, "r")
    assert live(conn, M, "SKU-1002") == 10_000 - 192
    c = actions.cancel_po(conn, run, r.po_id, "no longer needed")
    assert (c.ok, c.status) == (True, "WRITTEN")
    assert scalar(conn, "SELECT status FROM purchase_orders WHERE po_id = ?", r.po_id) == "CANCELLED"
    assert live(conn, M, "SKU-1002") == 10_000
    assert actions.cancel_po(conn, run, r.po_id, "again").status == "NOT_ALLOWED"


# --- scope and safety -----------------------------------------------------------------------------
def test_po_of_another_node_is_not_allowed():
    run, conn = new_run("S1-MODIFY", in_memory=True)
    conn.execute("INSERT INTO purchase_orders VALUES ('PO-S1', 'SUP-METRO', 'DS-SOUTH', 'SKU-1002', 100, NULL, 1.5, "
                 "'SUBMITTED', '2026-11-15', '2026-11-11', 'system', NULL, NULL)")
    for result in (actions.cancel_po(conn, run, "PO-S1", "r"), actions.modify_po(conn, run, "PO-S1", 120, 40, "r"),
                   actions.accept_partial_confirmation(conn, run, "PO-S1", "r"),
                   actions.escalate(conn, run, "OTHER", "x", {}, po_id="PO-S1")):
        assert (result.ok, result.status) == (False, "NOT_ALLOWED")
    assert scalar(conn, "SELECT status FROM purchase_orders WHERE po_id = 'PO-S1'") == "SUBMITTED"


def test_an_exception_rolls_the_whole_write_back(monkeypatch):
    run, conn = new_run("S1-MODIFY", in_memory=True)

    def boom(conn, po_id):
        raise RuntimeError("supplier down")

    monkeypatch.setattr(supplier_api, "submit", boom)
    pos, audits = scalar(conn, "SELECT COUNT(*) FROM purchase_orders"), scalar(conn, "SELECT COUNT(*) FROM audit_log")
    r = actions.create_po(conn, run, "SKU-1002", M, 192, 40, "r")
    assert (r.ok, r.status) == (False, "NOT_ALLOWED") and "supplier down" in r.message
    assert scalar(conn, "SELECT COUNT(*) FROM purchase_orders") == pos
    assert scalar(conn, "SELECT COUNT(*) FROM audit_log") == audits


@pytest.mark.parametrize("sid", ["S1-MODIFY", "S4-BUDGET"])
def test_every_attempt_is_audited_with_the_run_id(sid):
    run, conn = new_run(sid, in_memory=True)
    sku = scalar(conn, "SELECT sku FROM inventory")
    actions.create_po(conn, run, sku, M, 1, 40, "bad qty")
    actions.cancel_po(conn, run, "PO-NOPE", "r")
    rows = conn.execute("SELECT run_id, actor FROM audit_log").fetchall()
    assert len(rows) == 2 and {tuple(r) for r in rows} == {(run.run_id, "agent")}
