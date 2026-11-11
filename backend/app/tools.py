"""Tool registry: what the agent can look at and do, as plain functions with typed arguments.

Read tools map 1:1 to the info categories (D25), so "did it gather the right info?" is a set comparison.
Write tools are thin wrappers over actions.py. Bad input comes back as `{"ok": false, "error": ...}`
instead of an exception (D24), so a malformed call is feedback the model can fix.
The run is bound to one node, so tools take `sku`, never `node_id`.
"""
from __future__ import annotations

import json
import math
import sqlite3
from collections.abc import Callable
from dataclasses import asdict, dataclass, field, is_dataclass
from datetime import date
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from . import actions
from .calculations import check_inventory_consistency, demand_stats, plan_order
from .context import SkuContext, load_sku_context
from .db import SIM_TODAY, day
from .runs import Run


class ToolError(Exception):
    """A problem with the model's input; reported back as data."""


MAX_DAILY_DEMAND = 1_000_000  # units/day; far above any real SKU, keeps downstream math finite


class Args(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class RecArgs(Args):
    rec_id: str


class SkuArgs(Args):
    sku: str


class SalesArgs(Args):
    sku: str
    days: int = Field(28, ge=1, le=90, description="How many past days to return")


class ForecastArgs(Args):
    sku: str
    days: int = Field(14, ge=1, le=28, description="How many days ahead to return")


class EventsArgs(Args):
    po_id: str | None = None
    sku: str | None = None


class PlanArgs(Args):
    sku: str
    supplier_id: str
    daily_demand: float = Field(gt=0, le=MAX_DAILY_DEMAND, description="Units per day you choose to plan for")


class CreatePOArgs(Args):
    sku: str
    supplier_id: str
    qty: int
    daily_demand: float = Field(gt=0, le=MAX_DAILY_DEMAND, description="Units per day you planned for")
    reason: str = Field(min_length=1)
    justification: str | None = Field(None, description="Required to proceed when validation returns warnings")
    parent_po_id: str | None = Field(None, description="Set when this PO tops up an earlier PO for the same SKU")


class ModifyPOArgs(Args):
    po_id: str
    new_qty: int
    daily_demand: float = Field(gt=0, le=MAX_DAILY_DEMAND)
    reason: str = Field(min_length=1)
    justification: str | None = None


class PORefArgs(Args):
    po_id: str
    reason: str = Field(min_length=1)


class EscalateArgs(Args):
    kind: actions.AgentEscalationKind
    summary: str = Field(min_length=1)
    details: dict[str, Any] = Field(default_factory=dict)
    po_id: str | None = None


@dataclass(frozen=True)
class ToolCallRecord:
    name: str
    args: dict
    result: dict
    category: str | None
    ok: bool


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    args: type[BaseModel]  # one source for the JSON schema the model sees AND the validation we run (D27)
    category: str | None  # info category from scenarios.INFO_CATEGORIES; None for calc and write tools
    kind: str  # "read" | "calc" | "write"
    fn: Callable[[ToolSession, Any], dict]


def _day(offset: int) -> dict:
    """ISO date plus offset from today, so the model never does date arithmetic."""
    return {"date": day(offset), "day": offset}


def _offset(iso_date: str) -> int:
    return (date.fromisoformat(iso_date) - SIM_TODAY).days


def _json_safe(value: Any) -> Any:
    """Plain JSON types only. `inf` becomes "infinite"; NaN is left alone so a stray one fails loudly."""
    if isinstance(value, float):
        return "infinite" if math.isinf(value) else round(value, 2)
    if is_dataclass(value) and not isinstance(value, type):
        return _json_safe(asdict(value))
    if isinstance(value, dict):
        return {k: _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(v) for v in value]
    return value


def _readable(error: ValidationError) -> str:
    return "; ".join(f"{'.'.join(map(str, e['loc'])) or 'arguments'}: {e['msg']}" for e in error.errors())


@dataclass
class ToolSession:
    """One per run. Records every call for the Phase 4 trace and the Phase 5 scorer."""
    conn: sqlite3.Connection
    run: Run
    calls: list[ToolCallRecord] = field(default_factory=list)

    def ctx(self, sku: str) -> SkuContext:
        try:
            return load_sku_context(self.conn, self.run.node_id, sku)
        except KeyError:
            raise ToolError(f"Unknown SKU {sku!r}: {self.run.node_id} does not stock it") from None

    def call(self, name: str, args: dict) -> dict:
        """Run one tool. Never raises on bad model input."""
        tool = TOOLS.get(name)
        if tool is None:
            result = {"ok": False, "error": f"Unknown tool {name!r}. Available tools: {', '.join(TOOLS)}"}
        else:
            try:
                result = _json_safe(tool.fn(self, tool.args.model_validate(args)))
            except ValidationError as e:
                result = {"ok": False, "error": f"Invalid arguments for {name}: {_readable(e)}"}
            except ToolError as e:
                result = {"ok": False, "error": str(e)}
        self.calls.append(ToolCallRecord(name, args, result, tool.category if tool else None, result["ok"]))
        return result

    def openai_tools(self) -> list[dict]:
        return [{"type": "function", "function": {"name": t.name, "description": t.description,
                                                  "parameters": t.args.model_json_schema()}}
                for t in TOOLS.values()]

    @property
    def categories_read(self) -> set[str]:
        return {c.category for c in self.calls if c.ok and c.category}


# --- read tools ---------------------------------------------------------------------------------
def _get_recommendation(s: ToolSession, a: RecArgs) -> dict:
    r = s.conn.execute("SELECT * FROM recommendations WHERE rec_id = ? AND node_id = ?",
                       (a.rec_id, s.run.node_id)).fetchone()
    if r is None:
        raise ToolError(f"No recommendation {a.rec_id!r} at {s.run.node_id}")
    return {"ok": True, "rec_id": r["rec_id"], "sku": r["sku"], "supplier_id": r["supplier_id"],
            "recommended_qty": r["recommended_qty"], "engine_reason": r["reason"], "status": r["status"]}


def _get_product(s: ToolSession, a: SkuArgs) -> dict:
    c = s.ctx(a.sku)
    return {"ok": True, "sku": c.sku, "name": c.name, "category": c.category, "storage_zone": c.zone,
            "case_pack": c.case_pack, "shelf_life_days": c.shelf_life_days,
            "review_period_days": c.review_period_days, "safety_stock_days": c.safety_stock_days}


def _get_inventory(s: ToolSession, a: SkuArgs) -> dict:
    c = s.ctx(a.sku)
    return {"ok": True, "sku": c.sku, "on_hand": c.on_hand, "last_counted": _day(c.last_counted_day),
            "days_since_count": -c.last_counted_day,
            "data_quality_issues": [asdict(i) for i in check_inventory_consistency(c)]}


def _get_sales_history(s: ToolSession, a: SalesArgs) -> dict:
    c = s.ctx(a.sku)
    sales = c.sales[-a.days:]
    first = -len(sales)
    stats = demand_stats(c)
    return {"ok": True, "sku": c.sku,
            "daily_sales": [{**_day(first + i), "units": u} for i, u in enumerate(sales)],
            "demand_stats": {**asdict(stats),
                             "outlier_days": [{**_day(d), "units": u} for d, u in stats.outlier_days],
                             "promo_active_days": [_day(d) for d in stats.promo_active_days]}}


def _get_forecast(s: ToolSession, a: ForecastArgs) -> dict:
    c = s.ctx(a.sku)
    days = c.forecast[:a.days]
    return {"ok": True, "sku": c.sku, "daily_forecast": [{**_day(i), "units": u} for i, u in enumerate(days)],
            "mean_daily": sum(days) / len(days) if days else 0.0}


def _get_promotions(s: ToolSession, a: SkuArgs) -> dict:
    c = s.ctx(a.sku)
    return {"ok": True, "sku": c.sku, "promotions": [
        {"promo_id": p.promo_id, "start": _day(p.start_day), "end": _day(p.end_day), "description": p.description}
        for p in c.promotions if p.start_day <= 14 and p.end_day >= -28]}


def _get_purchase_orders(s: ToolSession, a: SkuArgs) -> dict:
    c = s.ctx(a.sku)
    return {"ok": True, "sku": c.sku,
            "open_pos": [{"po_id": p.po_id, "supplier_id": p.supplier_id, "status": p.status,
                          "qty_ordered": p.qty_ordered, "qty_confirmed": p.qty_confirmed,
                          "expected_qty": p.expected_qty, "arrival": _day(p.arrival_day)} for p in c.inbound],
            "receipts_since_last_count": [{"po_id": r.po_id, "qty": r.qty, "received": _day(r.day)}
                                          for r in c.receipts if r.day > c.last_counted_day]}


def _get_suppliers(s: ToolSession, a: SkuArgs) -> dict:
    c = s.ctx(a.sku)
    return {"ok": True, "sku": c.sku, "suppliers": [
        {"supplier_id": o.supplier_id, "name": o.name, "unit_cost": o.unit_cost, "moq": o.moq,
         "lead_time_days": o.lead_time_days, "listed_capacity": o.listed_capacity, "is_primary": o.is_primary,
         "is_approved": o.is_approved, "on_time_rate": o.on_time_rate, "fill_rate": o.fill_rate}
        for o in c.offers]}


def _get_budget(s: ToolSession, a: SkuArgs) -> dict:
    c = s.ctx(a.sku)
    row = s.conn.execute("SELECT budget_amount, spent_to_date FROM budgets WHERE category = ? AND period = ?",
                         (c.category, SIM_TODAY.strftime("%Y-%m"))).fetchone()
    amount, spent = (row["budget_amount"], row["spent_to_date"]) if row else (0.0, 0.0)
    return {"ok": True, "category": c.category, "budget_amount": amount, "spent_to_date": spent,
            "committed_on_open_pos": amount - spent - c.budget_remaining, "remaining": c.budget_remaining}


def _get_storage(s: ToolSession, a: SkuArgs) -> dict:
    c = s.ctx(a.sku)
    row = s.conn.execute("SELECT capacity_units, occupied_by_other_skus FROM storage_capacity "
                         "WHERE node_id = ? AND zone = ?", (c.node_id, c.zone)).fetchone()
    return {"ok": True, "zone": c.zone, "capacity": row["capacity_units"] if row else 0,
            "used_by_other_skus": row["occupied_by_other_skus"] if row else 0, "this_sku_on_hand": c.on_hand,
            "this_sku_inbound": c.inbound_qty, "free": c.storage_free}


def _get_supplier_events(s: ToolSession, a: EventsArgs) -> dict:
    if a.po_id is not None:
        po = s.conn.execute("SELECT sku FROM purchase_orders WHERE po_id = ? AND node_id = ?",
                            (a.po_id, s.run.node_id)).fetchone()
        if po is None:
            raise ToolError(f"No PO {a.po_id!r} at {s.run.node_id}")
        if a.sku is not None and po["sku"] != a.sku:
            raise ToolError(f"{a.po_id} is a PO for {po['sku']}, not {a.sku}")
    rows = s.conn.execute(
        "SELECT e.* FROM supplier_events e JOIN purchase_orders po ON po.po_id = e.po_id "
        "WHERE po.node_id = ? AND (? IS NULL OR e.po_id = ?) AND (? IS NULL OR po.sku = ?) "
        "ORDER BY e.created_at DESC, e.event_id DESC", (s.run.node_id, a.po_id, a.po_id, a.sku, a.sku)).fetchall()
    return {"ok": True, "events": [
        {"event_id": r["event_id"], "po_id": r["po_id"], "supplier_id": r["supplier_id"],
         "event_type": r["event_type"], "payload": json.loads(r["payload_json"]),
         "created": _day(_offset(r["created_at"]))} for r in rows]}


# --- calculator ---------------------------------------------------------------------------------
def _plan_order(s: ToolSession, a: PlanArgs) -> dict:
    c = s.ctx(a.sku)
    if c.offer(a.supplier_id) is None:
        raise ToolError(f"{a.supplier_id} does not offer {a.sku}")
    plan = plan_order(c, a.supplier_id, a.daily_demand)
    stockout = plan.projection_without_order.stockout_day
    return {"ok": True, "sku": c.sku, "supplier_id": a.supplier_id, "daily_demand": a.daily_demand,
            "coverage_days": plan.requirement.coverage_days, "target_stock": plan.requirement.target,
            "inventory_position": plan.requirement.position, "net_need": plan.requirement.net_need,
            "suggested_qty": plan.suggested_qty, "limits": asdict(plan.limits),
            "stockout_without_order": None if stockout is None else _day(stockout),
            "arrival": _day(plan.arrival_day)}


# --- write tools --------------------------------------------------------------------------------
def _action_dict(r: actions.ActionResult) -> dict:
    supplier = None
    if r.supplier is not None:
        supplier = {**asdict(r.supplier), "shortfall": r.supplier.requested - r.supplier.confirmed}
    return {"ok": r.ok, "status": r.status, "po_id": r.po_id, "escalation_id": r.escalation_id,
            "message": r.message, "violations": [asdict(v) for v in r.violations], "supplier": supplier}


def _create_po(s: ToolSession, a: CreatePOArgs) -> dict:
    return _action_dict(actions.create_po(s.conn, s.run, a.sku, a.supplier_id, a.qty, a.daily_demand, a.reason,
                                          a.justification, a.parent_po_id))


def _modify_po(s: ToolSession, a: ModifyPOArgs) -> dict:
    return _action_dict(actions.modify_po(s.conn, s.run, a.po_id, a.new_qty, a.daily_demand, a.reason,
                                          a.justification))


def _accept_partial(s: ToolSession, a: PORefArgs) -> dict:
    return _action_dict(actions.accept_partial_confirmation(s.conn, s.run, a.po_id, a.reason))


def _cancel_po(s: ToolSession, a: PORefArgs) -> dict:
    return _action_dict(actions.cancel_po(s.conn, s.run, a.po_id, a.reason))


def _escalate(s: ToolSession, a: EscalateArgs) -> dict:
    return _action_dict(actions.escalate(s.conn, s.run, a.kind, a.summary, a.details, a.po_id))


_TOOL_LIST = [
    Tool("get_recommendation", "The replenishment engine's recommendation and the reason it gives. "
         "The engine is not guaranteed to be right.", RecArgs, None, "read", _get_recommendation),
    Tool("get_product", "Product master: zone, case pack, shelf life, review and safety days.",
         SkuArgs, None, "read", _get_product),
    Tool("get_inventory", "On-hand units, when they were last counted, and data-quality issues "
         "(for example a record that recent receipts contradict).", SkuArgs, "inventory", "read", _get_inventory),
    Tool("get_sales_history", "Daily sales plus demand statistics: 7-day mean and median, trend, outlier days, "
         "promotion days, and the ratio to forecast.", SalesArgs, "sales_history", "read", _get_sales_history),
    Tool("get_forecast", "The upstream daily demand forecast and its mean.",
         ForecastArgs, "forecast", "read", _get_forecast),
    Tool("get_promotions", "Promotions overlapping the last 28 or next 14 days.",
         SkuArgs, "promotions", "read", _get_promotions),
    Tool("get_purchase_orders", "Open POs (expected quantity and arrival) and receipts since the last count.",
         SkuArgs, "open_pos", "read", _get_purchase_orders),
    Tool("get_suppliers", "Every supplier offer: cost, MOQ, lead time, listed capacity, approval, on-time and "
         "fill rate. Listed capacity is a catalog figure; only the supplier's confirmation is binding.",
         SkuArgs, "suppliers", "read", _get_suppliers),
    Tool("get_budget", "Category budget, spent, committed on open POs and remaining.",
         SkuArgs, "budget", "read", _get_budget),
    Tool("get_storage", "Zone capacity, used by other SKUs, this SKU on hand and inbound, and free space.",
         SkuArgs, "storage", "read", _get_storage),
    Tool("get_supplier_events", "Supplier messages, newest first, optionally for one PO or SKU.",
         EventsArgs, "supplier_events", "read", _get_supplier_events),
    Tool("plan_order", "Order-up-to calculator for a supplier and a daily demand you choose: target, position, "
         "net need, suggested quantity, every limit and the binding one, stockout day without the order.",
         PlanArgs, None, "calc", _plan_order),
    Tool("create_po", "Create a purchase order. It is validated first; errors block it, warnings need a "
         "justification, a PO above the approval limit waits for a human, and otherwise it is submitted and "
         "the supplier's confirmation is returned.", CreatePOArgs, None, "write", _create_po),
    Tool("modify_po", "Change the quantity of a PENDING_APPROVAL or SUBMITTED PO. Validated like a new PO.",
         ModifyPOArgs, None, "write", _modify_po),
    Tool("accept_partial_confirmation", "Accept what the supplier can ship on a PARTIALLY_CONFIRMED PO.",
         PORefArgs, None, "write", _accept_partial),
    Tool("cancel_po", "Cancel an open PO.", PORefArgs, None, "write", _cancel_po),
    Tool("escalate_to_human", "Ask a human to decide or investigate. Kinds: INVESTIGATION, BUDGET_INCREASE, "
         "SUPPLIER_ISSUE, OTHER.", EscalateArgs, None, "write", _escalate),
]
TOOLS: dict[str, Tool] = {t.name: t for t in _TOOL_LIST}
