"""DB -> facts. Loads everything about one node + SKU into one immutable SkuContext.

This is the only module in the domain core that touches SQL. Dates are converted to integer
offsets from SIM_TODAY here, once, so nothing downstream deals with dates.
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass, replace
from datetime import date

from .db import SIM_TODAY

# Open POs count as inbound stock and consume budget and storage.
OPEN_PO_STATUSES = ("PENDING_APPROVAL", "SUBMITTED", "CONFIRMED", "PARTIALLY_CONFIRMED")


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
    status: str
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


def _offset(iso_date: str) -> int:
    return (date.fromisoformat(iso_date) - SIM_TODAY).days


def load_sku_context(conn: sqlite3.Connection, node_id: str, sku: str) -> SkuContext:
    product = conn.execute("SELECT * FROM products WHERE sku = ?", (sku,)).fetchone()
    inv = conn.execute("SELECT on_hand, last_counted_at FROM inventory WHERE node_id = ? AND sku = ?",
                       (node_id, sku)).fetchone()
    if product is None or inv is None:
        raise KeyError(f"No product/inventory for {node_id} / {sku}")

    sales = tuple(r[0] for r in conn.execute(
        "SELECT units_sold FROM sales_history WHERE node_id = ? AND sku = ? ORDER BY date", (node_id, sku)))
    forecast = tuple(r[0] for r in conn.execute(
        "SELECT forecast_units FROM forecasts WHERE node_id = ? AND sku = ? ORDER BY date", (node_id, sku)))
    promotions = tuple(Promotion(r["promo_id"], _offset(r["start_date"]), _offset(r["end_date"]), r["description"])
                       for r in conn.execute("SELECT * FROM promotions WHERE node_id = ? AND sku = ? ORDER BY start_date",
                                             (node_id, sku)))

    marks = ", ".join("?" for _ in OPEN_PO_STATUSES)
    inbound = tuple(
        InboundPO(r["po_id"], r["supplier_id"], r["status"], r["qty_ordered"], r["qty_confirmed"],
                  r["unit_cost"], _offset(r["expected_arrival"]))
        for r in conn.execute(
            f"SELECT * FROM purchase_orders WHERE node_id = ? AND sku = ? AND status IN ({marks}) "
            "ORDER BY expected_arrival, po_id", (node_id, sku, *OPEN_PO_STATUSES)))
    receipts = tuple(
        Receipt(r["po_id"], r["qty_ordered"] if r["qty_confirmed"] is None else r["qty_confirmed"],
                _offset(r["expected_arrival"]))
        for r in conn.execute(
            "SELECT * FROM purchase_orders WHERE node_id = ? AND sku = ? AND status = 'RECEIVED' "
            "ORDER BY expected_arrival", (node_id, sku)))

    offers = tuple(
        SupplierOffer(r["supplier_id"], r["name"], r["unit_cost"], r["moq"], r["lead_time_days"],
                      r["listed_capacity_units"], bool(r["is_primary"]), bool(r["is_approved"]),
                      r["on_time_rate"], r["fill_rate"])
        for r in conn.execute(
            "SELECT sp.*, s.name, s.on_time_rate, s.fill_rate, s.is_approved FROM supplier_products sp "
            "JOIN suppliers s ON s.supplier_id = sp.supplier_id WHERE sp.sku = ? ORDER BY sp.supplier_id", (sku,)))

    # Budget is per category: every open PO in the category counts, not just this SKU's.
    budget = conn.execute("SELECT budget_amount - spent_to_date FROM budgets WHERE category = ? AND period = ?",
                          (product["category"], SIM_TODAY.strftime("%Y-%m"))).fetchone()
    open_value = conn.execute(
        f"SELECT COALESCE(SUM(COALESCE(po.qty_confirmed, po.qty_ordered) * po.unit_cost), 0) "
        f"FROM purchase_orders po JOIN products p ON p.sku = po.sku "
        f"WHERE p.category = ? AND po.status IN ({marks})", (product["category"], *OPEN_PO_STATUSES)).fetchone()[0]
    budget_remaining = (budget[0] if budget else 0.0) - open_value

    storage = conn.execute("SELECT capacity_units - occupied_by_other_skus FROM storage_capacity "
                           "WHERE node_id = ? AND zone = ?", (node_id, product["storage_zone"])).fetchone()
    storage_free = (storage[0] if storage else 0) - inv["on_hand"] - sum(po.expected_qty for po in inbound)

    return SkuContext(
        node_id=node_id, sku=sku, name=product["name"], category=product["category"],
        zone=product["storage_zone"], case_pack=product["case_pack"], shelf_life_days=product["shelf_life_days"],
        review_period_days=product["review_period_days"], safety_stock_days=product["safety_stock_days"],
        on_hand=inv["on_hand"], last_counted_day=_offset(inv["last_counted_at"]),
        sales=sales, forecast=forecast, promotions=promotions, inbound=inbound, receipts=receipts,
        offers=offers, budget_remaining=budget_remaining, storage_free=storage_free,
    )
