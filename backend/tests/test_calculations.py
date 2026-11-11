"""Unit tests on hand-made numbers (no DB)."""
import math

from app.calculations import (
    days_of_cover,
    order_up_to,
    project_stock,
    qty_limits,
    round_order_qty,
)
from app.context import InboundPO, SkuContext, SupplierOffer


def make_ctx(**over) -> SkuContext:
    base = {
        "node_id": "N", "sku": "S", "name": "Thing", "category": "Cat", "zone": "ambient", "case_pack": 10, "shelf_life_days": None,
        "review_period_days": 7, "safety_stock_days": 3, "on_hand": 100, "last_counted_day": 0, "sales": (10,) * 28,
        "forecast": (10.0,) * 28, "promotions": (), "inbound": (), "receipts": (), "offers": (), "budget_remaining": 1000.0,
        "storage_free": 500,
    }
    return SkuContext(**{**base, **over})


def make_offer(**over) -> SupplierOffer:
    base = {"supplier_id": "SUP", "name": "Sup", "unit_cost": 2.0, "moq": 50, "lead_time_days": 5, "listed_capacity": 1000,
                "is_primary": True, "is_approved": True, "on_time_rate": 0.95, "fill_rate": 0.95}
    return SupplierOffer(**{**base, **over})


def test_order_up_to():
    r = order_up_to(40, 5, 7, 3, on_hand=220, inbound=200)
    assert (r.coverage_days, r.target, r.position, r.net_need) == (15, 600, 420, 180)


def test_order_up_to_never_negative():
    assert order_up_to(10, 5, 7, 3, on_hand=500, inbound=0).net_need == 0


def test_round_order_qty_zero_need():
    assert round_order_qty(0, 24, 120) == 0


def test_round_order_qty_below_moq_goes_up_to_moq():
    assert round_order_qty(42, 6, 30) == 42
    assert round_order_qty(10, 6, 30) == 30


def test_round_order_qty_moq_not_a_case_multiple():
    assert round_order_qty(10, 12, 50) == 60


def test_round_order_qty_rounds_need_up_to_case():
    assert round_order_qty(180, 24, 120) == 192


def test_project_stock_stockout_before_arrival():
    p = project_stock(100, 10, {15: 500})
    assert p.stockout_day == 10  # 100 units last days 0-9, day 10 can't be met
    assert p.end_levels[9] == 0


def test_project_stock_arrival_in_time_prevents_stockout():
    p = project_stock(100, 10, {9: 500}, horizon=28)
    assert p.stockout_day is None
    assert p.end_levels[9] == 500


def test_project_stock_stockout_after_arrival():
    p = project_stock(100, 10, {5: 100})
    assert p.stockout_day == 20


def test_project_stock_never_stocks_out():
    assert project_stock(1000, 10, {}).stockout_day is None


def test_days_of_cover():
    assert days_of_cover(100, 40) == 2.5
    assert days_of_cover(100, 0) == math.inf


def test_without_po_adds_back_budget_and_storage():
    po = InboundPO("PO-1", "SUP", "CONFIRMED", 200, 150, 2.0, 3)
    ctx = make_ctx(inbound=(po,), budget_remaining=1000.0, storage_free=500)
    freed = ctx.without_po("PO-1")
    assert freed.inbound == ()
    assert freed.budget_remaining == 1300.0  # confirmed qty 150 x $2
    assert freed.storage_free == 650
    assert ctx.inbound_qty == 150 and freed.inbound_qty == 0


def test_qty_limits_binding_and_flooring():
    ctx = make_ctx(budget_remaining=500.0, storage_free=283)
    lim = qty_limits(ctx, make_offer(), daily_demand=10)
    assert (lim.budget, lim.storage, lim.supplier_capacity, lim.shelf_life) == (250, 280, 1000, None)
    assert (lim.binding, lim.max_qty) == ("budget", 250)


def test_qty_limits_shelf_life():
    ctx = make_ctx(shelf_life_days=10, on_hand=30, case_pack=6)
    lim = qty_limits(ctx, make_offer(), daily_demand=12)
    assert lim.shelf_life == 90  # 12 x 10 - 30
    assert lim.binding == "shelf_life"


def test_qty_limits_never_negative():
    ctx = make_ctx(storage_free=-40, shelf_life_days=2, on_hand=100)
    lim = qty_limits(ctx, make_offer(), daily_demand=10)
    assert lim.storage == 0 and lim.shelf_life == 0 and lim.max_qty == 0
