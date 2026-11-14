"""Builds each scenario DB and checks the hand-worked examples end to end."""
from dataclasses import replace

import pytest

from app.purchasing.calculations import (
    check_inventory_consistency,
    days_of_cover,
    demand_stats,
    plan_order,
)
from app.purchasing.context import load_sku_context
from app.purchasing.policy import approval_for
from app.purchasing.validator import validate_purchase
from app.scenarios.catalog import SCENARIOS
from app.scenarios.seed import build_scenario_db

N = "DS-NORTH"


def ctx_for(sid: str, sku: str):
    return load_sku_context(build_scenario_db(sid, ":memory:"), N, sku)


def codes(result, severity=None):
    return {v.code for v in result.violations if severity is None or v.severity == severity}


def test_s1_modify():
    ctx = ctx_for("S1-MODIFY", "SKU-1002")
    plan = plan_order(ctx, "SUP-METRO", 40)
    assert plan.requirement.position == 420
    assert (plan.requirement.target, plan.requirement.net_need, plan.suggested_qty) == (600, 180, 192)
    assert plan.limits.storage == 264

    big = validate_purchase(ctx, "SUP-METRO", 800, 40)
    assert not big.ok
    assert "OVER_STORAGE" in codes(big, "error") and "EXCESS_COVER" in codes(big, "warning")
    storage = next(v for v in big.violations if v.code == "OVER_STORAGE")
    assert storage.details == {"requested": 800, "free": 280, "max_qty": 264}
    assert big.post_order_cover_days == pytest.approx(30.5)

    good = validate_purchase(ctx, "SUP-METRO", 192, 40)
    assert good.ok and not good.violations
    assert good.po_value == pytest.approx(288)
    assert approval_for(good.po_value).auto_submit


def test_s1_accept():
    ctx = ctx_for("S1-ACCEPT", "SKU-1001")
    plan = plan_order(ctx, "SUP-METRO", 50)
    assert plan.requirement.position == 270
    assert plan.requirement.net_need == 480 and plan.suggested_qty == 480
    res = validate_purchase(ctx, "SUP-METRO", 480, 50)
    assert res.ok and res.po_value == pytest.approx(960)
    assert approval_for(res.po_value).auto_submit
    assert "ARRIVES_AFTER_STOCKOUT" not in codes(res)


def test_s1_reject():
    ctx = ctx_for("S1-REJECT", "SKU-1003")
    plan = plan_order(ctx, "SUP-METRO", 20)
    assert plan.requirement.position == 700
    assert plan.requirement.net_need == 0 and plan.suggested_qty == 0
    assert days_of_cover(plan.requirement.position, 20) == 35


def test_s1_investigate_is_flagged():
    issues = check_inventory_consistency(ctx_for("S1-INVESTIGATE", "SKU-1004"))
    assert [i.code for i in issues] == ["INVENTORY_RECORD_SUSPECT"]
    assert issues[0].details["on_hand"] == 0
    assert issues[0].details["expected_floor"] == 309


@pytest.mark.parametrize("sid", [s for s in SCENARIOS if s != "S1-INVESTIGATE"])
def test_other_scenarios_have_no_data_quality_issues(sid):
    conn = build_scenario_db(sid, ":memory:")
    sku = conn.execute("SELECT sku FROM inventory").fetchone()[0]
    assert check_inventory_consistency(load_sku_context(conn, N, sku)) == []


def test_s2_source_elsewhere():
    ctx = ctx_for("S2-SOURCE-ELSEWHERE", "SKU-2001")
    needs = {s: plan_order(ctx, s, 40) for s in ("SUP-QUICK", "SUP-RAPIDO", "SUP-METRO")}
    assert all(p.requirement.position == 430 for p in needs.values())
    assert [needs[s].suggested_qty for s in ("SUP-QUICK", "SUP-RAPIDO", "SUP-METRO")] == [90, 130, 210]

    assert "SUPPLIER_NOT_APPROVED" in codes(validate_purchase(ctx, "SUP-SHADY", 50, 40), "error")
    assert "BELOW_MOQ" in codes(validate_purchase(ctx, "SUP-BULK", 130, 40), "error")

    bulk = validate_purchase(ctx, "SUP-BULK", 200, 40)
    assert bulk.ok and codes(bulk, "warning") == {"LOW_RELIABILITY_SUPPLIER", "ARRIVES_AFTER_STOCKOUT"}
    stockout = next(v for v in bulk.violations if v.code == "ARRIVES_AFTER_STOCKOUT")
    assert stockout.details == {"stockout_day": 10, "arrival_day": 12}

    quick = validate_purchase(ctx, "SUP-QUICK", 90, 40)
    assert quick.ok and not quick.violations


def test_s2_accept_short():
    ctx = ctx_for("S2-ACCEPT-SHORT", "SKU-2002")
    for offer in ctx.offers:
        plan = plan_order(ctx, offer.supplier_id, 15)
        assert plan.requirement.position == 550
        assert plan.requirement.net_need == 0 and plan.suggested_qty == 0


def test_s2_alt_also_short_validator_cannot_see_live_availability():
    ctx = ctx_for("S2-ALT-ALSO-SHORT", "SKU-2003")
    assert validate_purchase(ctx, "SUP-QUICK", 90, 40).ok


def test_s3_sustained_spike():
    ctx = ctx_for("S3-SUSTAINED-SPIKE", "SKU-3001")
    stats = demand_stats(ctx)
    assert stats.median_7d == 77
    assert stats.mean_7d == pytest.approx(74.3, abs=0.1)
    assert stats.ratio_vs_forecast == pytest.approx(77 / 30)
    assert stats.trend_7d > 0
    assert stats.outlier_days == () and stats.promo_active_days == ()

    plan = plan_order(ctx, "SUP-METRO", stats.mean_7d)
    assert plan.requirement.net_need == pytest.approx(414.5, abs=1)
    assert plan.suggested_qty == 420

    res = validate_purchase(ctx, "SUP-METRO", 720, stats.mean_7d, replaces_po_id="PO-3001")
    assert res.ok


def test_a_single_bulk_day_is_an_outlier_and_the_median_ignores_it():
    """The demand statistics the agent reads: one 260-unit day drags the mean, not the median."""
    base = ctx_for("S3-PROMO-ENDING", "SKU-3003")
    ctx = replace(base, promotions=(), sales=(28, 27, 28, 33, 28, 28, 260))
    stats = demand_stats(ctx)
    assert stats.outlier_days == ((-1, 260),)
    assert stats.median_7d == 28
    assert stats.mean_7d == pytest.approx(61.7, abs=0.1)


def test_s3_promo_ending():
    ctx = ctx_for("S3-PROMO-ENDING", "SKU-3003")
    stats = demand_stats(ctx)
    assert stats.promo_active_days == tuple(range(-7, 0))
    assert stats.outlier_days == ()
    req = plan_order(ctx, "SUP-METRO", 25).requirement
    assert req.position == 620 and req.net_need == 0


def test_s4_budget():
    ctx = ctx_for("S4-BUDGET", "SKU-4001")
    plan = plan_order(ctx, "SUP-METRO", 60)
    assert plan.requirement.net_need == 570 and plan.suggested_qty == 576
    assert plan.limits.budget == 396 and plan.limits.binding == "budget"

    over = validate_purchase(ctx, "SUP-METRO", 576, 60)
    assert "OVER_BUDGET" in codes(over, "error")
    assert over.po_value == pytest.approx(3456)

    fits = validate_purchase(ctx, "SUP-METRO", 396, 60)
    assert fits.ok and fits.po_value == pytest.approx(2376)
    assert not approval_for(fits.po_value).auto_submit


def test_s4_moq_vs_shelf_life():
    ctx = ctx_for("S4-MOQ-VS-SHELF-LIFE", "SKU-4002")
    dairy = plan_order(ctx, "SUP-DAIRY", 12)
    assert dairy.suggested_qty == 180
    assert dairy.limits.shelf_life == 90
    res = validate_purchase(ctx, "SUP-DAIRY", 180, 12)
    shelf = next(v for v in res.violations if v.code == "OVER_SHELF_LIFE")
    assert shelf.severity == "error"
    assert (shelf.details["units_after_order"], shelf.details["cover_days"]) == (210, 17.5)

    assert plan_order(ctx, "SUP-FARM", 12).suggested_qty == 42
    assert validate_purchase(ctx, "SUP-FARM", 42, 12).ok


def test_validator_unit_rules():
    ctx = ctx_for("S1-MODIFY", "SKU-1002")
    assert "QTY_NOT_POSITIVE" in codes(validate_purchase(ctx, "SUP-METRO", 0, 40), "error")
    assert codes(validate_purchase(ctx, "SUP-NOBODY", 120, 40)) == {"SUPPLIER_NOT_OFFERING"}
    assert "NOT_CASE_MULTIPLE" in codes(validate_purchase(ctx, "SUP-METRO", 130, 40), "error")
    assert "OVER_SUPPLIER_CAPACITY" in codes(validate_purchase(ctx, "SUP-METRO", 10_008, 40), "error")


def test_unknown_replaces_po_id_is_a_violation_not_an_exception():
    ctx = ctx_for("S3-SUSTAINED-SPIKE", "SKU-3001")
    res = validate_purchase(ctx, "SUP-METRO", 720, 74.3, replaces_po_id="PO-NOPE")
    assert not res.ok
    nf = [v for v in res.violations if v.code == "PO_NOT_FOUND"]
    assert len(nf) == 1 and nf[0].severity == "error"
    assert "PO-NOPE" in nf[0].message and "not an open PO" in nf[0].message
    assert nf[0].details == {"replaces_po_id": "PO-NOPE"}
    # other rules are still reported alongside it
    assert "PO_NOT_FOUND" in codes(validate_purchase(ctx, "SUP-NOBODY", 720, 74.3, replaces_po_id="PO-NOPE"))


def test_valid_replaces_po_id_has_no_po_not_found():
    ctx = ctx_for("S3-SUSTAINED-SPIKE", "SKU-3001")
    res = validate_purchase(ctx, "SUP-METRO", 720, 74.3, replaces_po_id="PO-3001")
    assert res.ok and "PO_NOT_FOUND" not in codes(res)


def test_without_po_unknown_id_raises_key_error():
    ctx = ctx_for("S3-SUSTAINED-SPIKE", "SKU-3001")
    with pytest.raises(KeyError, match="PO-NOPE"):
        ctx.without_po("PO-NOPE")


def test_approval_threshold_is_inclusive_of_the_limit():
    assert approval_for(2000.0).auto_submit
    decision = approval_for(2376.0)
    assert not decision.auto_submit
    assert decision.reason == "PO value $2,376 exceeds auto-approval limit $2,000"
