"""Hard rules. Checks a proposed purchase against the SkuContext and returns ALL violations at once.

Errors block the write; warnings are allowed but returned so the agent has to justify them.
The validator only knows what a real buyer knows: it never sees the supplier's live availability.
"""
from __future__ import annotations

from dataclasses import dataclass

from .calculations import days_of_cover, inbound_arrivals, project_stock, qty_limits
from .context import SkuContext

EXCESS_COVER_FACTOR = 2.0  # warn when post-order cover exceeds this x the coverage window
LOW_RELIABILITY_ON_TIME = 0.80  # warn when a supplier's on-time rate is below this


@dataclass(frozen=True)
class Violation:
    code: str
    severity: str  # "error" (blocks) | "warning" (allowed, agent must justify)
    message: str
    details: dict


@dataclass(frozen=True)
class ValidationResult:
    ok: bool  # True if no "error"
    violations: tuple[Violation, ...]
    po_value: float
    post_order_cover_days: float
    arrival_day: int  # 0 when the supplier has no offer for the SKU


def _error(code: str, message: str, **details) -> Violation:
    return Violation(code, "error", message, details)


def _warning(code: str, message: str, **details) -> Violation:
    return Violation(code, "warning", message, details)


def validate_purchase(ctx: SkuContext, supplier_id: str, qty: int, daily_demand: float,
                      *, replaces_po_id: str | None = None) -> ValidationResult:
    """With `replaces_po_id`, "change PO X to qty Q" is validated as a fresh PO of Q."""
    not_found: list[Violation] = []
    if replaces_po_id is not None:
        if any(p.po_id == replaces_po_id for p in ctx.inbound):
            ctx = ctx.without_po(replaces_po_id)
        else:
            not_found.append(_error("PO_NOT_FOUND",
                                    f"{replaces_po_id} is not an open PO for {ctx.node_id} / {ctx.sku}",
                                    replaces_po_id=replaces_po_id))

    offer = ctx.offer(supplier_id)
    position = ctx.on_hand + ctx.inbound_qty
    post_cover = days_of_cover(position + qty, daily_demand)
    if offer is None:
        v = _error("SUPPLIER_NOT_OFFERING", f"{supplier_id} does not offer {ctx.sku}", supplier_id=supplier_id)
        return ValidationResult(False, (*not_found, v), 0.0, post_cover, 0)

    po_value = qty * offer.unit_cost
    arrival_day = offer.lead_time_days
    limits = qty_limits(ctx, offer, daily_demand)
    out: list[Violation] = list(not_found)

    if qty <= 0:
        out.append(_error("QTY_NOT_POSITIVE", f"Quantity must be positive, got {qty}", requested=qty))
    if not offer.is_approved:
        out.append(_error("SUPPLIER_NOT_APPROVED", f"{offer.name} is not an approved supplier", supplier_id=supplier_id))
    if qty < offer.moq:
        out.append(_error("BELOW_MOQ", f"{qty} is below {offer.name}'s MOQ of {offer.moq}",
                          requested=qty, moq=offer.moq))
    if qty % ctx.case_pack != 0:
        out.append(_error("NOT_CASE_MULTIPLE", f"{qty} is not a multiple of the case pack {ctx.case_pack}",
                          requested=qty, case_pack=ctx.case_pack))
    if qty > offer.listed_capacity:
        out.append(_error("OVER_SUPPLIER_CAPACITY", f"{qty} exceeds {offer.name}'s listed capacity {offer.listed_capacity}",
                          requested=qty, capacity=offer.listed_capacity, max_qty=limits.supplier_capacity))
    if po_value > ctx.budget_remaining:
        out.append(_error("OVER_BUDGET",
                          f"PO value ${po_value:,.2f} exceeds the remaining {ctx.category} budget ${ctx.budget_remaining:,.2f}",
                          po_value=po_value, budget_remaining=ctx.budget_remaining, max_qty=limits.budget))
    if qty > ctx.storage_free:
        out.append(_error("OVER_STORAGE", f"{qty} units exceed the {ctx.storage_free} units of free {ctx.zone} storage",
                          requested=qty, free=ctx.storage_free, max_qty=limits.storage))
    if ctx.shelf_life_days is not None and post_cover > ctx.shelf_life_days:
        out.append(_error("OVER_SHELF_LIFE",
                          f"{position + qty} units at {daily_demand:g}/day is {post_cover:.1f} days of cover, "
                          f"more than the {ctx.shelf_life_days}-day shelf life",
                          units_after_order=position + qty, cover_days=post_cover,
                          shelf_life_days=ctx.shelf_life_days, max_qty=limits.shelf_life))

    coverage_days = arrival_day + ctx.review_period_days + ctx.safety_stock_days
    if post_cover > EXCESS_COVER_FACTOR * coverage_days:
        out.append(_warning("EXCESS_COVER",
                            f"Post-order cover is {post_cover:.1f} days, over {EXCESS_COVER_FACTOR:g} x the "
                            f"{coverage_days}-day coverage window",
                            cover_days=post_cover, coverage_days=coverage_days))
    stockout_day = project_stock(ctx.on_hand, daily_demand, inbound_arrivals(ctx)).stockout_day
    if stockout_day is not None and stockout_day < arrival_day:
        out.append(_warning("ARRIVES_AFTER_STOCKOUT",
                            f"Projected stockout on day {stockout_day} is before this PO arrives on day {arrival_day}",
                            stockout_day=stockout_day, arrival_day=arrival_day))
    if offer.on_time_rate < LOW_RELIABILITY_ON_TIME:
        out.append(_warning("LOW_RELIABILITY_SUPPLIER",
                            f"{offer.name} delivers on time only {offer.on_time_rate:.0%} of the time",
                            on_time_rate=offer.on_time_rate))

    return ValidationResult(not any(v.severity == "error" for v in out), tuple(out), po_value, post_cover, arrival_day)
