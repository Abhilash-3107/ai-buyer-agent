"""DB -> facts. Loads everything about one node + SKU into one immutable SkuContext.

This is the purchasing read model: the SQL that feeds the rules. Dates are converted to integer
offsets from SIM_TODAY here, once, so nothing downstream deals with dates.
"""
from __future__ import annotations

import sqlite3

from ..db import SIM_TODAY, offset
from .types import (
    OPEN_PO_STATUSES,
    InboundPO,
    Promotion,
    Receipt,
    SkuContext,
    SupplierOffer,
)


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
    promotions = tuple(Promotion(r["promo_id"], offset(r["start_date"]), offset(r["end_date"]), r["description"])
                       for r in conn.execute("SELECT * FROM promotions WHERE node_id = ? AND sku = ? ORDER BY start_date",
                                             (node_id, sku)))

    marks = ", ".join("?" for _ in OPEN_PO_STATUSES)
    inbound = tuple(
        InboundPO(r["po_id"], r["supplier_id"], r["status"], r["qty_ordered"], r["qty_confirmed"],
                  r["unit_cost"], offset(r["expected_arrival"]))
        for r in conn.execute(
            f"SELECT * FROM purchase_orders WHERE node_id = ? AND sku = ? AND status IN ({marks}) "
            "ORDER BY expected_arrival, po_id", (node_id, sku, *OPEN_PO_STATUSES)))
    receipts = tuple(
        Receipt(r["po_id"], r["qty_ordered"] if r["qty_confirmed"] is None else r["qty_confirmed"],
                offset(r["expected_arrival"]))
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
        on_hand=inv["on_hand"], last_counted_day=offset(inv["last_counted_at"]),
        sales=sales, forecast=forecast, promotions=promotions, inbound=inbound, receipts=receipts,
        offers=offers, budget_remaining=budget_remaining, storage_free=storage_free,
    )
