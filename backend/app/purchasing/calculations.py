"""Pure maths on plain numbers (plus the SkuContext facts). No SQL, no LLM.

The caller chooses the daily demand rate (forecast vs recent sales is a judgement call);
everything here is the formula given that choice.
"""
from __future__ import annotations

import math
import statistics

from .types import (
    DataQualityIssue,
    DemandStats,
    OrderPlan,
    Projection,
    QtyLimits,
    Requirement,
    SkuContext,
    SupplierOffer,
)

OUTLIER_FACTOR = 2.5  # a day is an outlier if units > this x the 7-day median
INVENTORY_SUSPECT_RATIO = 0.5  # on_hand below this share of the receipts-implied floor is suspect
FORECAST_WINDOW_DAYS = 14


def _mean(values) -> float:
    return statistics.fmean(values) if values else 0.0


def demand_stats(ctx: SkuContext) -> DemandStats:
    """Safe for a new SKU: no sales gives zeros, one sales day gives a flat trend, no forecast gives ratio inf."""
    last7 = ctx.sales[-7:]
    first_day = -len(last7)
    forecast_daily = _mean(ctx.forecast[:FORECAST_WINDOW_DAYS])
    median_7d = statistics.median(last7) if last7 else 0.0
    y_mean = _mean(last7)

    trend = 0.0
    if len(last7) >= 2:
        x_mean = (len(last7) - 1) / 2
        trend = (sum((i - x_mean) * (y - y_mean) for i, y in enumerate(last7))
                 / sum((i - x_mean) ** 2 for i in range(len(last7))))

    return DemandStats(
        forecast_daily=forecast_daily,
        mean_7d=y_mean,
        median_7d=median_7d,
        mean_28d=_mean(ctx.sales[-28:]),
        trend_7d=trend,
        ratio_vs_forecast=median_7d / forecast_daily if forecast_daily else math.inf,
        outlier_days=tuple((first_day + i, u) for i, u in enumerate(last7) if u > OUTLIER_FACTOR * median_7d),
        promo_active_days=tuple(d for d in range(first_day, 0)
                                if any(p.start_day <= d <= p.end_day for p in ctx.promotions)),
    )


def order_up_to(daily_demand: float, lead_time: int, review: int, safety: int,
                on_hand: int, inbound: int) -> Requirement:
    coverage = lead_time + review + safety
    target = daily_demand * coverage
    position = on_hand + inbound
    return Requirement(daily_demand, coverage, target, position, max(0.0, target - position))


def round_order_qty(net_need: float, case_pack: int, moq: int) -> int:
    if net_need <= 0:
        return 0
    return math.ceil(max(net_need, moq) / case_pack) * case_pack


def project_stock(on_hand: int, daily_demand: float, arrivals: dict[int, int], horizon: int = 28) -> Projection:
    """Arrivals land at the start of their day, then the day's demand is sold."""
    stock = float(on_hand)
    levels: list[float] = []
    stockout_day = None
    for d in range(horizon):
        stock += arrivals.get(d, 0) - daily_demand
        levels.append(stock)
        if stock < 0 and stockout_day is None:
            stockout_day = d
    return Projection(stockout_day, tuple(levels))


def inbound_arrivals(ctx: SkuContext) -> dict[int, int]:
    """Open POs by arrival day. An overdue PO (past day) is treated as landing today."""
    arrivals: dict[int, int] = {}
    for po in ctx.inbound:
        day = max(po.arrival_day, 0)
        arrivals[day] = arrivals.get(day, 0) + po.expected_qty
    return arrivals


def days_of_cover(units: float, daily_demand: float) -> float:
    return math.inf if daily_demand == 0 else units / daily_demand


def floor_to_case(units: int, case_pack: int) -> int:
    return max(0, units // case_pack * case_pack)


def qty_limits(ctx: SkuContext, offer: SupplierOffer, daily_demand: float) -> QtyLimits:
    limits: dict[str, int | None] = {
        "budget": floor_to_case(math.floor(ctx.budget_remaining / offer.unit_cost), ctx.case_pack),
        "storage": floor_to_case(ctx.storage_free, ctx.case_pack),
        "supplier_capacity": floor_to_case(offer.listed_capacity, ctx.case_pack),
        "shelf_life": None if ctx.shelf_life_days is None else floor_to_case(
            math.floor(daily_demand * ctx.shelf_life_days - (ctx.on_hand + ctx.inbound_qty)), ctx.case_pack),
    }
    binding, max_qty = min(((k, v) for k, v in limits.items() if v is not None), key=lambda kv: kv[1])
    return QtyLimits(**limits, binding=binding, max_qty=max_qty)


def plan_order(ctx: SkuContext, supplier_id: str, daily_demand: float) -> OrderPlan:
    offer = ctx.offer(supplier_id)
    if offer is None:
        raise KeyError(f"{supplier_id} does not offer {ctx.sku}")
    req = order_up_to(daily_demand, offer.lead_time_days, ctx.review_period_days, ctx.safety_stock_days,
                      ctx.on_hand, ctx.inbound_qty)
    return OrderPlan(
        supplier_id=supplier_id,
        requirement=req,
        suggested_qty=round_order_qty(req.net_need, ctx.case_pack, offer.moq),
        limits=qty_limits(ctx, offer, daily_demand),
        projection_without_order=project_stock(ctx.on_hand, daily_demand, inbound_arrivals(ctx)),
        arrival_day=offer.lead_time_days,
    )


def check_inventory_consistency(ctx: SkuContext) -> list[DataQualityIssue]:
    """Flag an on-hand record that a later receipt makes implausible (e.g. a stale count of 0)."""
    issues = []
    for r in ctx.receipts:
        if r.day <= ctx.last_counted_day:
            continue
        sold_since = sum(ctx.sales[r.day:]) if r.day < 0 else 0
        expected_floor = r.qty - sold_since
        if ctx.on_hand < INVENTORY_SUSPECT_RATIO * expected_floor:
            issues.append(DataQualityIssue(
                code="INVENTORY_RECORD_SUSPECT",
                message=(f"On-hand is {ctx.on_hand} (counted day {ctx.last_counted_day}) but {r.po_id} received "
                         f"{r.qty} units on day {r.day} and only {sold_since} were sold since, "
                         f"so about {expected_floor} should be on hand."),
                details={"on_hand": ctx.on_hand, "last_counted_day": ctx.last_counted_day, "po_id": r.po_id,
                         "received_qty": r.qty, "received_day": r.day, "sold_since": sold_since,
                         "expected_floor": expected_floor},
            ))
    return issues
