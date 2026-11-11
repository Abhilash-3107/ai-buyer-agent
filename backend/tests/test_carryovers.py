"""Phase 3 carry-overs: a modified PO is judged on its own arrival day, and a supplier REJECTED cannot look like success."""
from app import actions
from app.context import load_sku_context
from app.runs import new_run
from app.tools import ToolSession
from app.validator import validate_purchase


def warning_codes(result):
    return {v.code for v in result.violations if v.severity == "warning"}


def test_arrival_day_override_replaces_the_lead_time_arrival():
    run, conn = new_run("S3-SUSTAINED-SPIKE", in_memory=True)  # Metro leads 5 days; PO-3001 lands on day 4
    ctx = load_sku_context(conn, run.node_id, run.sku)
    default = validate_purchase(ctx, "SUP-METRO", 300, 100, replaces_po_id="PO-3001")
    own = validate_purchase(ctx, "SUP-METRO", 300, 100, replaces_po_id="PO-3001", arrival_day=4)
    assert "ARRIVES_AFTER_STOCKOUT" in warning_codes(default) and default.arrival_day == 5
    assert "ARRIVES_AFTER_STOCKOUT" not in warning_codes(own) and own.arrival_day == 4


def test_modify_po_uses_the_pos_own_arrival_day():
    run, conn = new_run("S3-SUSTAINED-SPIKE", in_memory=True)
    result = actions.modify_po(conn, run, "PO-3001", 300, 100, "demand is higher")
    assert result.status == "WRITTEN"  # lead-time arrival (day 5) would have asked for a justification


def test_supplier_rejected_is_not_ok_at_the_top_level():
    run, conn = new_run("S2-SOURCE-ELSEWHERE", in_memory=True)  # Metro has nothing live
    result = ToolSession(conn, run).call("create_po", {"sku": "SKU-2001", "supplier_id": "SUP-METRO", "qty": 100,
                                                       "daily_demand": 40, "reason": "r"})
    assert result["ok"] is False and result["status"] == "WRITTEN" and result["supplier"]["status"] == "REJECTED"
    assert result["shortfall"] == 100 and "REJECTED" in result["message"]


def test_a_full_confirmation_has_no_shortfall():
    run, conn = new_run("S1-MODIFY", in_memory=True)
    result = ToolSession(conn, run).call("create_po", {"sku": "SKU-1002", "supplier_id": "SUP-METRO", "qty": 192,
                                                       "daily_demand": 40, "reason": "r"})
    assert result["ok"] is True and result["shortfall"] == 0
