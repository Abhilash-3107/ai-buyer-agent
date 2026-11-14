"""Tool layer: schemas, arg checking, JSON-safe results, categories, and the Phase 2 carry-over fixes."""
import json
from dataclasses import replace

import pytest

from app.agent.runs import new_run
from app.agent.tools import TOOLS, ToolSession
from app.purchasing.calculations import demand_stats
from app.purchasing.context import load_sku_context
from app.purchasing.validator import validate_purchase
from app.scenarios.catalog import SCENARIOS
from app.scenarios.types import INFO_CATEGORIES


def session(sid):
    run, conn = new_run(sid, in_memory=True)
    return ToolSession(conn, run)


def call(s, name, **args):
    result = s.call(name, args)
    json.dumps(result, allow_nan=False)  # a stray NaN or inf must fail loudly
    return result


def count(s, table):
    return s.conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]


def sku_of(s):
    return s.conn.execute("SELECT sku FROM inventory").fetchone()[0]


# --- registry -------------------------------------------------------------------------------------
def test_one_read_tool_per_info_category():
    read = [t for t in TOOLS.values() if t.kind == "read" and t.category]
    assert {t.category for t in read} == INFO_CATEGORIES and len(read) == len(INFO_CATEGORIES)
    assert all(t.category is None for t in TOOLS.values() if t.kind != "read")


def test_openai_specs_come_from_the_pydantic_models():
    specs = {t["function"]["name"]: t["function"] for t in session("S1-MODIFY").openai_tools()}
    assert set(specs) == set(TOOLS)
    assert specs["create_po"]["parameters"]["required"] == ["sku", "supplier_id", "qty", "daily_demand", "reason"]
    for name in ("create_po", "modify_po", "accept_partial_confirmation", "cancel_po"):
        assert "reason" in specs[name]["parameters"]["required"]
    assert specs["escalate_to_human"]["parameters"]["properties"]["kind"]["enum"] == [
        "INVESTIGATION", "BUDGET_INCREASE", "SUPPLIER_ISSUE", "OTHER"]
    assert all(t["type"] == "function" for t in session("S1-MODIFY").openai_tools())


@pytest.mark.parametrize("sid", list(SCENARIOS))
def test_every_read_tool_runs_and_is_json_safe(sid):
    s = session(sid)
    sku = sku_of(s)
    for t in TOOLS.values():
        if t.kind == "read" and "sku" in t.args.model_fields:
            assert call(s, t.name, sku=sku)["ok"], t.name
    assert call(s, "get_supplier_events")["ok"]
    assert call(s, "get_product", sku=sku)["ok"]
    assert call(s, "plan_order", sku=sku, supplier_id=s.conn.execute(
        "SELECT supplier_id FROM supplier_products WHERE sku = ?", (sku,)).fetchone()[0], daily_demand=30)["ok"]
    assert s.categories_read == INFO_CATEGORIES


# --- categories and trace -------------------------------------------------------------------------
def test_categories_read_tracks_successful_reads_only():
    s = session("S1-MODIFY")
    call(s, "get_inventory", sku="SKU-1002")
    call(s, "get_budget", sku="SKU-1002")
    call(s, "get_product", sku="SKU-1002")  # no category
    call(s, "get_forecast", sku="SKU-NOPE")  # failed, so it does not count
    assert s.categories_read == {"inventory", "budget"}
    assert [(c.name, c.ok) for c in s.calls] == [("get_inventory", True), ("get_budget", True),
                                                 ("get_product", True), ("get_forecast", False)]
    assert s.calls[0].category == "inventory" and s.calls[0].args == {"sku": "SKU-1002"}


# --- read tool content ----------------------------------------------------------------------------
def test_s1_investigate_inventory_is_flagged():
    s = session("S1-INVESTIGATE")
    r = call(s, "get_inventory", sku="SKU-1004")
    assert [i["code"] for i in r["data_quality_issues"]] == ["INVENTORY_RECORD_SUSPECT"]
    assert r["on_hand"] == 0 and r["last_counted"] == {"date": "2026-11-02", "day": -9}
    assert call(s, "get_purchase_orders", sku="SKU-1004")["receipts_since_last_count"] == [
        {"po_id": "PO-1401", "qty": 400, "received": {"date": "2026-11-09", "day": -2}}]


def test_suppliers_never_expose_live_availability():
    s = session("S2-ALT-ALSO-SHORT")
    r = call(s, "get_suppliers", sku="SKU-2003")
    quick = next(x for x in r["suppliers"] if x["supplier_id"] == "SUP-QUICK")
    assert quick["listed_capacity"] == 1000
    assert "available" not in json.dumps(r)


def test_recommendation_and_budget_and_storage():
    s = session("S1-MODIFY")
    rec = call(s, "get_recommendation", rec_id="REC-1002")
    assert (rec["recommended_qty"], rec["sku"]) == (800, "SKU-1002") and "20 days" in rec["engine_reason"]
    b = call(s, "get_budget", sku="SKU-1002")
    assert (b["budget_amount"], b["spent_to_date"], b["committed_on_open_pos"], b["remaining"]) == (5000, 3200, 300, 1500)
    st = call(s, "get_storage", sku="SKU-1002")
    assert (st["capacity"], st["used_by_other_skus"], st["this_sku_on_hand"], st["this_sku_inbound"], st["free"]) \
        == (2000, 1300, 220, 200, 280)


def test_sales_forecast_and_promotions():
    s = session("S3-PROMO-ENDING")
    sales = call(s, "get_sales_history", sku="SKU-3003", days=7)
    assert len(sales["daily_sales"]) == 7 and sales["daily_sales"][-1]["day"] == -1
    assert sales["demand_stats"]["promo_active_days"][0] == {"date": "2026-11-04", "day": -7}
    fc = call(s, "get_forecast", sku="SKU-3003", days=3)
    assert len(fc["daily_forecast"]) == 3 and fc["mean_daily"] == 25
    promo = call(s, "get_promotions", sku="SKU-3003")["promotions"]
    assert [p["promo_id"] for p in promo] == ["PROMO-77"] and promo[0]["end"]["day"] == 1


def test_supplier_events_newest_first_and_filters():
    s = session("S2-SOURCE-ELSEWHERE")
    r = call(s, "get_supplier_events", po_id="PO-2001")
    assert [e["event_id"] for e in r["events"]] == ["EVT-PO-2001"]
    assert r["events"][0]["payload"]["qty_confirmed"] == 250
    assert call(s, "get_supplier_events", sku="SKU-2001")["events"] == r["events"]
    assert call(s, "get_supplier_events", sku="SKU-9999")["events"] == []
    call(s, "create_po", sku="SKU-2001", supplier_id="SUP-QUICK", qty=90, daily_demand=40, reason="r")
    newest = call(s, "get_supplier_events")["events"]
    assert {e["po_id"] for e in newest} == {"PO-A001", "PO-2001"}
    assert newest[0]["created"] == {"date": "2026-11-11", "day": 0}


def test_plan_order_tool():
    s = session("S1-MODIFY")
    r = call(s, "plan_order", sku="SKU-1002", supplier_id="SUP-METRO", daily_demand=40)
    assert (r["target_stock"], r["inventory_position"], r["net_need"], r["suggested_qty"]) == (600, 420, 180, 192)
    assert r["limits"]["storage"] == 264 and r["limits"]["binding"] == "storage"
    assert r["stockout_without_order"] == {"date": "2026-11-21", "day": 10}  # even PO-1101 only lasts until then
    assert r["arrival"] == {"date": "2026-11-16", "day": 5}
    late = call(session("S2-SOURCE-ELSEWHERE"), "plan_order", sku="SKU-2001", supplier_id="SUP-BULK", daily_demand=40)
    assert late["stockout_without_order"]["day"] == 10 and late["arrival"]["day"] == 12


@pytest.mark.parametrize("demand", [float("inf"), "inf", "1e400", 1e308, float("nan")])
def test_non_finite_or_huge_daily_demand_is_an_error_result(demand):
    r = call(session("S1-MODIFY"), "plan_order", sku="SKU-1002", supplier_id="SUP-METRO", daily_demand=demand)
    assert r["ok"] is False and r["error"]


def test_infinite_values_become_the_string_infinite():
    s = session("S1-MODIFY")
    s.conn.execute("DELETE FROM forecasts")
    r = call(s, "get_sales_history", sku="SKU-1002")
    assert r["demand_stats"]["ratio_vs_forecast"] == "infinite" and r["demand_stats"]["forecast_daily"] == 0


# --- write tools ----------------------------------------------------------------------------------
def test_write_tools_return_the_action_result_as_a_dict():
    s = session("S1-MODIFY")
    args = {"sku": "SKU-1002", "supplier_id": "SUP-METRO", "daily_demand": 40, "reason": "r"}
    blocked = call(s, "create_po", qty=800, **args)
    assert (blocked["ok"], blocked["status"], blocked["supplier"]) == (False, "BLOCKED", None)
    assert "OVER_STORAGE" in {v["code"] for v in blocked["violations"]}
    ok = call(s, "create_po", qty=192, **args)
    assert (ok["ok"], ok["status"], ok["po_id"]) == (True, "WRITTEN", "PO-A001")
    assert ok["supplier"] == {"po_id": "PO-A001", "requested": 192, "confirmed": 192, "status": "CONFIRMED",
                              "message": ok["message"], "shortfall": 0}


def test_write_tool_shows_the_shortfall():
    s = session("S2-ALT-ALSO-SHORT")
    r = call(s, "create_po", sku="SKU-2003", supplier_id="SUP-QUICK", qty=90, daily_demand=40, reason="r")
    assert (r["supplier"]["confirmed"], r["supplier"]["shortfall"], r["supplier"]["status"]) \
        == (40, 50, "PARTIALLY_CONFIRMED")


def test_other_write_tools():
    s = session("S2-ACCEPT-SHORT")
    assert call(s, "accept_partial_confirmation", po_id="PO-2002", reason="covered")["ok"]
    s = session("S1-MODIFY")
    assert call(s, "modify_po", po_id="PO-1101", new_qty=100, daily_demand=40, reason="r")["status"] == "NOT_ALLOWED"
    assert call(s, "cancel_po", po_id="PO-1101", reason="r")["ok"]
    esc = call(s, "escalate_to_human", kind="INVESTIGATION", summary="count the shelf", details={"sku": "SKU-1002"})
    assert esc["ok"] and esc["escalation_id"] == "ESC-001"


# --- bad input ------------------------------------------------------------------------------------
@pytest.mark.parametrize("name,args,expected", [
    ("no_such_tool", {}, "Unknown tool 'no_such_tool'"),
    ("get_inventory", {}, "sku: Field required"),
    ("get_inventory", {"sku": 123}, "sku: Input should be a valid string"),
    ("get_inventory", {"sku": "SKU-1002", "node_id": "DS-SOUTH"}, "node_id: Extra inputs are not permitted"),
    ("get_inventory", {"sku": "SKU-NOPE"}, "Unknown SKU 'SKU-NOPE'"),
    ("get_sales_history", {"sku": "SKU-1002", "days": "many"}, "days: Input should be a valid integer"),
    ("get_sales_history", {"sku": "SKU-1002", "days": 0}, "days"),
    ("get_recommendation", {"rec_id": "REC-NOPE"}, "No recommendation 'REC-NOPE'"),
    ("plan_order", {"sku": "SKU-1002", "supplier_id": "SUP-NOBODY", "daily_demand": 40}, "does not offer"),
    ("plan_order", {"sku": "SKU-1002", "supplier_id": "SUP-METRO", "daily_demand": 0}, "daily_demand"),
    ("get_supplier_events", {"po_id": "PO-NOPE"}, "No PO 'PO-NOPE'"),
    ("create_po", {"sku": "SKU-1002", "supplier_id": "SUP-METRO", "qty": "lots", "daily_demand": 40, "reason": "r"},
     "qty: Input should be a valid integer"),
    ("create_po", {"sku": "SKU-1002", "supplier_id": "SUP-METRO", "qty": 24, "daily_demand": 40}, "reason: Field required"),
    ("create_po", {"sku": "SKU-NOPE", "supplier_id": "SUP-METRO", "qty": 24, "daily_demand": 40, "reason": "r"},
     "does not stock SKU-NOPE"),
    ("modify_po", {"po_id": "PO-NOPE", "new_qty": 24, "daily_demand": 40, "reason": "r"}, "is not a PO"),
    ("cancel_po", {"po_id": "PO-NOPE", "reason": "r"}, "is not a PO"),
    ("escalate_to_human", {"kind": "APPROVAL", "summary": "x"}, "kind: Input should be"),
    ("escalate_to_human", {"kind": "OTHER", "summary": "x", "po_id": "PO-NOPE"}, "is not a PO"),
])
def test_bad_input_is_an_error_result_and_never_writes(name, args, expected):
    s = session("S1-MODIFY")
    before = {t: count(s, t) for t in ("purchase_orders", "escalations", "supplier_events")}
    result = call(s, name, **args)
    assert result["ok"] is False
    message = result.get("error") or result["message"]
    assert expected in message
    assert {t: count(s, t) for t in before} == before


def test_po_of_another_sku_is_rejected_by_the_supplier_events_filter():
    s = session("S2-SOURCE-ELSEWHERE")
    r = call(s, "get_supplier_events", po_id="PO-2001", sku="SKU-9999")
    assert r["ok"] is False and "not SKU-9999" in r["error"]


# --- Phase 2 carry-over ---------------------------------------------------------------------------
def bare_ctx(**changes):
    run, conn = new_run("S1-MODIFY", in_memory=True)
    return replace(load_sku_context(conn, run.node_id, "SKU-1002"), **changes)


@pytest.mark.parametrize("sales,forecast", [((), ()), ((30,), ()), ((), (40.0,) * 14), ((30,), (40.0,) * 14)])
def test_demand_stats_survives_new_skus(sales, forecast):
    stats = demand_stats(bare_ctx(sales=sales, forecast=forecast))
    assert stats.trend_7d == 0
    assert stats.outlier_days == ()
    assert stats.forecast_daily == (40 if forecast else 0)
    assert stats.ratio_vs_forecast == (pytest.approx(30 / 40) if sales and forecast else
                                       0 if forecast else float("inf"))
    if not sales:
        assert (stats.mean_7d, stats.median_7d, stats.mean_28d) == (0, 0, 0)


def test_unknown_supplier_no_longer_hides_other_rule_checks():
    ctx = bare_ctx()
    res = validate_purchase(ctx, "SUP-NOBODY", -5, 40)
    assert {v.code for v in res.violations} == {"SUPPLIER_NOT_OFFERING", "QTY_NOT_POSITIVE", "NOT_CASE_MULTIPLE"}
    over = validate_purchase(ctx, "SUP-NOBODY", 288, 40)
    assert {v.code for v in over.violations} == {"SUPPLIER_NOT_OFFERING", "OVER_STORAGE"}
    assert not over.ok and over.po_value == 0
