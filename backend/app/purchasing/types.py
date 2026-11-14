"""Purchasing vocabulary: the immutable facts, results and constants shared by the rules and the write pipeline.

Stdlib only. The loaders, formulas and writers that produce these live in the sibling modules.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from enum import StrEnum
from pathlib import Path
from typing import Literal, get_args


class PoStatus(StrEnum):
    """Purchase order lifecycle, as stored in purchase_orders.status."""
    PENDING_APPROVAL = "PENDING_APPROVAL"
    SUBMITTED = "SUBMITTED"
    CONFIRMED = "CONFIRMED"
    PARTIALLY_CONFIRMED = "PARTIALLY_CONFIRMED"
    REJECTED = "REJECTED"
    RECEIVED = "RECEIVED"
    CANCELLED = "CANCELLED"


class ActionStatus(StrEnum):
    """What a write action reports back to the agent, the API and the trace."""
    WRITTEN = "WRITTEN"
    BLOCKED = "BLOCKED"
    NEEDS_JUSTIFICATION = "NEEDS_JUSTIFICATION"
    PENDING_APPROVAL = "PENDING_APPROVAL"
    NOT_ALLOWED = "NOT_ALLOWED"


class Severity(StrEnum):
    ERROR = "error"  # blocks the write
    WARNING = "warning"  # allowed, the agent must justify


# Open POs count as inbound stock and consume budget and storage.
OPEN_PO_STATUSES = (PoStatus.PENDING_APPROVAL, PoStatus.SUBMITTED, PoStatus.CONFIRMED, PoStatus.PARTIALLY_CONFIRMED)
MODIFIABLE_STATUSES = (PoStatus.PENDING_APPROVAL, PoStatus.SUBMITTED)  # D23: never after the supplier has answered
AgentEscalationKind = Literal["INVESTIGATION", "BUDGET_INCREASE", "SUPPLIER_ISSUE", "OTHER"]
AGENT_ESCALATION_KINDS = get_args(AgentEscalationKind)


@dataclass(frozen=True)
class Run:
    run_id: str
    scenario_id: str
    node_id: str  # the one node this run may read and write, taken from the trigger
    sku: str  # the product the trigger is about, taken from the data like the node
    path: Path


@dataclass(frozen=True)
class SupplierOffer:
    supplier_id: str
    name: str
    unit_cost: float
    moq: int
    lead_time_days: int
    listed_capacity: int
    is_primary: bool
    is_approved: bool
    on_time_rate: float
    fill_rate: float


@dataclass(frozen=True)
class InboundPO:
    po_id: str
    supplier_id: str
    status: str  # a PoStatus value as read from the DB
    qty_ordered: int
    qty_confirmed: int | None
    unit_cost: float
    arrival_day: int  # offset from today

    @property
    def expected_qty(self) -> int:
        """A supplier's confirmation overrides what we asked for."""
        return self.qty_ordered if self.qty_confirmed is None else self.qty_confirmed


@dataclass(frozen=True)
class Receipt:
    """A RECEIVED PO, kept for the inventory data-quality check."""
    po_id: str
    qty: int
    day: int  # < 0 = in the past


@dataclass(frozen=True)
class Promotion:
    promo_id: str
    start_day: int
    end_day: int
    description: str


@dataclass(frozen=True)
class SkuContext:
    node_id: str
    sku: str
    name: str
    category: str
    zone: str
    case_pack: int
    shelf_life_days: int | None
    review_period_days: int
    safety_stock_days: int
    on_hand: int
    last_counted_day: int
    sales: tuple[int, ...]  # oldest -> newest, last item = yesterday
    forecast: tuple[float, ...]  # index 0 = today
    promotions: tuple[Promotion, ...]
    inbound: tuple[InboundPO, ...]  # open POs for this node + sku
    receipts: tuple[Receipt, ...]
    offers: tuple[SupplierOffer, ...]  # every supplier that sells this SKU, approved or not
    budget_remaining: float  # amount - spent - value of all open POs in the category
    storage_free: int  # zone capacity - other SKUs - on_hand - inbound

    @property
    def inbound_qty(self) -> int:
        return sum(po.expected_qty for po in self.inbound)

    def offer(self, supplier_id: str) -> SupplierOffer | None:
        return next((o for o in self.offers if o.supplier_id == supplier_id), None)

    def without_po(self, po_id: str) -> SkuContext:
        """Same facts with one open PO removed, so "change PO X to qty Q" can be validated as a fresh PO."""
        po = next((p for p in self.inbound if p.po_id == po_id), None)
        if po is None:
            raise KeyError(f"{po_id} is not an open PO for {self.node_id} / {self.sku}")
        return replace(
            self,
            inbound=tuple(p for p in self.inbound if p.po_id != po_id),
            budget_remaining=self.budget_remaining + po.expected_qty * po.unit_cost,
            storage_free=self.storage_free + po.expected_qty,
        )


@dataclass(frozen=True)
class DemandStats:
    forecast_daily: float  # mean of the forecast over the next 14 days
    mean_7d: float
    median_7d: float
    mean_28d: float
    trend_7d: float  # least-squares slope over the last 7 days, units/day per day
    ratio_vs_forecast: float  # median_7d / forecast_daily (median, so one outlier can't drive it)
    outlier_days: tuple[tuple[int, int], ...]  # (day_offset, units) where units > 2.5 x median_7d
    promo_active_days: tuple[int, ...]  # last-7 day offsets covered by a promotion


@dataclass(frozen=True)
class Requirement:
    daily_demand: float
    coverage_days: int  # lead + review + safety
    target: float
    position: int
    net_need: float


@dataclass(frozen=True)
class Projection:
    stockout_day: int | None  # first day the stock can't meet that day's demand; None if never in horizon
    end_levels: tuple[float, ...]  # stock at the end of each day 0..horizon-1


@dataclass(frozen=True)
class QtyLimits:
    """The biggest legal order under each constraint, already floored to a case pack."""
    budget: int
    storage: int
    supplier_capacity: int
    shelf_life: int | None  # None for non-perishables
    binding: str  # name of the tightest limit
    max_qty: int


@dataclass(frozen=True)
class OrderPlan:
    """One-call summary for the agent's calculator tool."""
    supplier_id: str
    requirement: Requirement
    suggested_qty: int
    limits: QtyLimits
    projection_without_order: Projection
    arrival_day: int  # = offer.lead_time_days


@dataclass(frozen=True)
class DataQualityIssue:
    code: str
    message: str
    details: dict


@dataclass(frozen=True)
class Violation:
    code: str
    severity: Severity
    message: str
    details: dict


@dataclass(frozen=True)
class ValidationResult:
    ok: bool  # True if no "error"
    violations: tuple[Violation, ...]
    po_value: float
    post_order_cover_days: float
    arrival_day: int  # 0 when the supplier has no offer for the SKU


@dataclass(frozen=True)
class ApprovalDecision:
    auto_submit: bool
    reason: str


@dataclass(frozen=True)
class SupplierResponse:
    po_id: str
    requested: int
    confirmed: int
    status: PoStatus  # CONFIRMED | PARTIALLY_CONFIRMED | REJECTED
    message: str


@dataclass(frozen=True)
class ActionResult:
    ok: bool
    status: ActionStatus
    po_id: str | None
    violations: tuple[Violation, ...]
    supplier: SupplierResponse | None  # what the supplier actually confirmed (loop 2)
    message: str
    escalation_id: str | None = None  # set when a human queue entry was opened
    steps: tuple[dict, ...] = ()  # harness steps that ran: {stage: validator | approval | supplier, status, detail}
