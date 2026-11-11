"""Tiny DSL for writing scenario data readably.

Each scenario in scenarios.py is a function that calls these helpers, e.g.
    b.stock("DS-NORTH", "SKU-1002", on_hand=220)
    b.forecast("DS-NORTH", "SKU-1002", per_day=40)
so the numbers that drive the story are visible at a glance.
"""
from __future__ import annotations

import json
import random
import sqlite3

from .db import SIM_TODAY, day


def steady(rate: float, days: int, jitter: float = 0.1, seed: int = 0) -> list[int]:
    """Realistic-looking daily sales around `rate` (±jitter), deterministic via seed."""
    rng = random.Random(seed)
    return [max(0, round(rate * (1 + rng.uniform(-jitter, jitter)))) for _ in range(days)]


class Builder:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def _ins(self, table: str, **cols) -> None:
        keys = ", ".join(cols)
        marks = ", ".join("?" for _ in cols)
        self.conn.execute(f"INSERT INTO {table} ({keys}) VALUES ({marks})", tuple(cols.values()))

    # --- master data -------------------------------------------------------
    def node(self, node_id: str, name: str, city: str) -> None:
        self._ins("nodes", node_id=node_id, name=name, city=city)

    def supplier(self, supplier_id: str, name: str, on_time: float, fill: float, approved: bool = True) -> None:
        self._ins("suppliers", supplier_id=supplier_id, name=name, on_time_rate=on_time,
                  fill_rate=fill, is_approved=int(approved))

    def product(self, sku: str, name: str, category: str, *, zone: str = "ambient", case_pack: int = 1,
                shelf_life: int | None = None, review: int = 7, safety: int = 3) -> None:
        self._ins("products", sku=sku, name=name, category=category, storage_zone=zone,
                  case_pack=case_pack, shelf_life_days=shelf_life, review_period_days=review,
                  safety_stock_days=safety)

    def offer(self, supplier_id: str, sku: str, *, cost: float, moq: int, lead: int,
              listed_capacity: int = 10_000, primary: bool = False, live_available: int | None = None) -> None:
        """Supplier terms for a SKU. `live_available` = what the supplier will REALLY confirm
        (hidden from the agent); defaults to the listed capacity."""
        self._ins("supplier_products", supplier_id=supplier_id, sku=sku, unit_cost=cost, moq=moq,
                  lead_time_days=lead, listed_capacity_units=listed_capacity, is_primary=int(primary))
        self._ins("supplier_live_availability", supplier_id=supplier_id, sku=sku,
                  available_units=listed_capacity if live_available is None else live_available)

    # --- operational data --------------------------------------------------
    def stock(self, node_id: str, sku: str, on_hand: int, counted_days_ago: int = 0) -> None:
        self._ins("inventory", node_id=node_id, sku=sku, on_hand=on_hand, last_counted_at=day(-counted_days_ago))

    def sales(self, node_id: str, sku: str, daily: list[int]) -> None:
        """Past daily sales, oldest first, ending yesterday."""
        n = len(daily)
        for i, units in enumerate(daily):
            self._ins("sales_history", node_id=node_id, sku=sku, date=day(i - n), units_sold=units)

    def forecast(self, node_id: str, sku: str, per_day: float, days: int = 28) -> None:
        """Flat daily forecast from today forward (flat keeps the math hand-checkable)."""
        for i in range(days):
            self._ins("forecasts", node_id=node_id, sku=sku, date=day(i), forecast_units=per_day)

    def promo(self, promo_id: str, node_id: str, sku: str, start: int, end: int, description: str) -> None:
        self._ins("promotions", promo_id=promo_id, node_id=node_id, sku=sku,
                  start_date=day(start), end_date=day(end), description=description)

    def storage(self, node_id: str, zone: str, capacity: int, other_skus: int) -> None:
        self._ins("storage_capacity", node_id=node_id, zone=zone, capacity_units=capacity,
                  occupied_by_other_skus=other_skus)

    def budget(self, category: str, amount: float, spent: float) -> None:
        self._ins("budgets", category=category, period=SIM_TODAY.strftime("%Y-%m"),
                  budget_amount=amount, spent_to_date=spent)

    def po(self, po_id: str, supplier_id: str, node_id: str, sku: str, qty: int, cost: float, *,
           status: str, arrives_in: int, confirmed: int | None = None, created_days_ago: int = 3,
           created_by: str = "system", notes: str | None = None) -> None:
        self._ins("purchase_orders", po_id=po_id, supplier_id=supplier_id, node_id=node_id, sku=sku,
                  qty_ordered=qty, qty_confirmed=confirmed, unit_cost=cost, status=status,
                  expected_arrival=day(arrives_in), created_at=day(-created_days_ago),
                  created_by=created_by, parent_po_id=None, notes=notes)

    def recommendation(self, rec_id: str, node_id: str, sku: str, supplier_id: str, qty: int, reason: str) -> None:
        self._ins("recommendations", rec_id=rec_id, node_id=node_id, sku=sku, supplier_id=supplier_id,
                  recommended_qty=qty, reason=reason, created_at=day(0))

    def supplier_event(self, event_id: str, po_id: str, supplier_id: str, event_type: str, payload: dict) -> None:
        self._ins("supplier_events", event_id=event_id, po_id=po_id, supplier_id=supplier_id,
                  event_type=event_type, payload_json=json.dumps(payload), created_at=day(0))
