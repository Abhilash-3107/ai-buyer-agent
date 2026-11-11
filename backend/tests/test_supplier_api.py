"""The mock supplier confirms against hidden live availability, deterministically."""
import pytest

from app import supplier_api
from app.runs import new_run


def live(conn, supplier, sku):
    return conn.execute("SELECT available_units FROM supplier_live_availability WHERE supplier_id = ? AND sku = ?",
                        (supplier, sku)).fetchone()[0]


def submitted_po(conn, po_id, supplier, sku, qty, status="SUBMITTED"):
    conn.execute("INSERT INTO purchase_orders VALUES (?, ?, 'DS-NORTH', ?, ?, NULL, 1.0, ?, '2026-11-15', "
                 "'2026-11-11', 'agent', NULL, NULL)", (po_id, supplier, sku, qty, status))


def test_full_confirmation_uses_up_availability_and_leaves_an_event_and_audit_row():
    run, conn = new_run("S1-MODIFY", in_memory=True)
    submitted_po(conn, "PO-T1", "SUP-METRO", "SKU-1002", 192)
    before = live(conn, "SUP-METRO", "SKU-1002")
    resp = supplier_api.submit(conn, "PO-T1")
    assert (resp.requested, resp.confirmed, resp.status) == (192, 192, "CONFIRMED")
    assert live(conn, "SUP-METRO", "SKU-1002") == before - 192
    po = conn.execute("SELECT status, qty_confirmed FROM purchase_orders WHERE po_id = 'PO-T1'").fetchone()
    assert (po["status"], po["qty_confirmed"]) == ("CONFIRMED", 192)
    event = conn.execute("SELECT event_type FROM supplier_events WHERE po_id = 'PO-T1'").fetchone()
    assert event["event_type"] == "CONFIRMATION"
    audit = conn.execute("SELECT run_id, actor, action FROM audit_log").fetchall()
    assert [tuple(r) for r in audit] == [(run.run_id, "supplier_api", "PO_CONFIRMED")]


def test_partial_confirmation_reports_the_shortfall():
    _, conn = new_run("S2-ALT-ALSO-SHORT", in_memory=True)
    submitted_po(conn, "PO-T1", "SUP-QUICK", "SKU-2003", 90)
    resp = supplier_api.submit(conn, "PO-T1")
    assert (resp.confirmed, resp.status) == (40, "PARTIALLY_CONFIRMED")
    assert "short by 50" in resp.message
    assert live(conn, "SUP-QUICK", "SKU-2003") == 0
    assert conn.execute("SELECT event_type FROM supplier_events WHERE po_id = 'PO-T1'").fetchone()[0] \
        == "PARTIAL_CONFIRMATION"


def test_no_availability_rejects():
    _, conn = new_run("S2-SOURCE-ELSEWHERE", in_memory=True)  # Metro's live availability is 0
    submitted_po(conn, "PO-T1", "SUP-METRO", "SKU-2001", 100)
    resp = supplier_api.submit(conn, "PO-T1")
    assert (resp.confirmed, resp.status) == (0, "REJECTED")
    assert conn.execute("SELECT status FROM purchase_orders WHERE po_id = 'PO-T1'").fetchone()[0] == "REJECTED"


def test_same_input_gives_the_same_answer():
    answers = []
    for _ in range(2):
        _, conn = new_run("S2-ALT-ALSO-SHORT", in_memory=True)
        submitted_po(conn, "PO-T1", "SUP-QUICK", "SKU-2003", 90)
        r = supplier_api.submit(conn, "PO-T1")
        answers.append((r.confirmed, r.status, r.message))
    assert answers[0] == answers[1]


def test_submit_refuses_a_po_that_is_not_submitted():
    _, conn = new_run("S1-MODIFY", in_memory=True)
    submitted_po(conn, "PO-T1", "SUP-METRO", "SKU-1002", 192, status="PENDING_APPROVAL")
    with pytest.raises(ValueError, match="not a SUBMITTED PO"):
        supplier_api.submit(conn, "PO-T1")
    with pytest.raises(ValueError):
        supplier_api.submit(conn, "PO-NOPE")


def test_release_gives_confirmed_units_back():
    _, conn = new_run("S1-MODIFY", in_memory=True)
    submitted_po(conn, "PO-T1", "SUP-METRO", "SKU-1002", 192)
    before = live(conn, "SUP-METRO", "SKU-1002")
    supplier_api.submit(conn, "PO-T1")
    supplier_api.release(conn, "PO-T1")
    assert live(conn, "SUP-METRO", "SKU-1002") == before
