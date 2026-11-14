"""Scenario catalogue: the 4 assignment scenarios, each with variants.

Why variants? An agent that always says "MODIFY" would pass a single test. Each
scenario therefore has at least one case where the *right* answer is to leave
the plan alone (ACCEPT/REJECT) - so we measure judgement, not just activity.

Every scenario carries an `Expected` block worked out BY HAND with the standard
order-up-to replenishment formula (implemented for real in Phase 2):

    target_stock   = daily_demand x (lead_time + review_period + safety_days)
    inventory_pos  = on_hand + open inbound POs (confirmed qty if the supplier responded, else ordered qty)
    net_need       = max(0, target_stock - inventory_pos)
    order_qty      = 0 if net_need is 0, else net_need rounded UP to case pack, and at least the MOQ

The eval (Phase 5) compares the agent's actions against these expectations.
"""
from __future__ import annotations

from collections.abc import Callable

from .builder import Builder, steady
from .types import ACCEPT, INVESTIGATE, MODIFY, REJECT, Expected, Scenario

N = "DS-NORTH"  # every scenario plays out at this dark store


# ---------------------------------------------------------------------------
# Shared world: nodes + supplier master (same in every scenario)
# ---------------------------------------------------------------------------
def base_world(b: Builder, ambient: tuple[int, int] = (5000, 3000)) -> None:
    """`ambient` = (capacity, units taken by other SKUs) for the ambient zone."""
    b.node("DS-NORTH", "Dark Store North", "Bogotá")
    b.node("DS-SOUTH", "Dark Store South", "Bogotá")
    #           id            name                     on-time fill  approved
    b.supplier("SUP-METRO",  "Metro Wholesale",        0.95,   0.97)
    b.supplier("SUP-QUICK",  "QuickSupply Express",    0.93,   0.96)
    b.supplier("SUP-RAPIDO", "Rapido Distributors",    0.90,   0.94)
    b.supplier("SUP-BULK",   "BulkBuy Traders",        0.72,   0.80)
    b.supplier("SUP-DAIRY",  "DairyDirect",            0.97,   0.98)
    b.supplier("SUP-FARM",   "FarmFresh Co-op",        0.91,   0.95)
    b.supplier("SUP-SHADY",  "Unverified Imports Ltd", 0.55,   0.60, approved=False)
    b.storage(N, "ambient", capacity=ambient[0], other_skus=ambient[1])
    b.storage(N, "chilled", capacity=800, other_skus=400)


SCENARIOS: dict[str, Scenario] = {}


def scenario(**kw):
    def register(fn: Callable[[Builder], None]):
        assert kw["id"] not in SCENARIOS, f"duplicate scenario id {kw['id']}"
        SCENARIOS[kw["id"]] = Scenario(build=fn, **kw)
        return fn
    return register


# ===========================================================================
# SCENARIO 1 - Purchase recommendation review
# ===========================================================================
@scenario(
    id="S1-MODIFY", group=1,
    title="Recommendation ignores stock on hand and inbound PO",
    situation="The replenishment engine recommends buying 800 units of Potato Chips 150g (SKU-1002) "
              "from Metro Wholesale for Dark Store North. Review the recommendation.",
    summary="The engine wants 800 bags of chips, but it forgot the 220 on hand and 200 arriving. The real need is about 192, and 800 would not even fit in storage.",
    trigger={"type": "RECOMMENDATION_REVIEW", "rec_id": "REC-1002"},
    expected=Expected(
        decision=MODIFY,
        required_info=("inventory", "forecast", "open_pos", "suppliers", "storage", "budget"),
        new_buy_qty=(168, 240),
        allowed_suppliers=("SUP-METRO",),
        worked_example=(
            "target = 40/day x (5 lead + 7 review + 3 safety) = 600. "
            "position = 220 on hand + 200 inbound (PO-1101) = 420. net need = 180 -> 8 cases of 24 = 192. "
            "800 would also exceed free storage (2000 cap - 1300 other SKUs - 420 this SKU = 280 free) "
            "and leave ~30 days of cover. Engine computed 20 days x 40 = 800 and forgot on-hand + inbound."
        ),
    ),
)
def _s1_modify(b: Builder) -> None:
    base_world(b, ambient=(2000, 1300))  # tight store: 280 units free for this SKU
    b.product("SKU-1002", "Potato Chips Classic 150g", "Snacks", case_pack=24)
    b.offer("SUP-METRO", "SKU-1002", cost=1.50, moq=120, lead=5, primary=True)
    b.stock(N, "SKU-1002", on_hand=220)
    b.sales(N, "SKU-1002", steady(40, 28, seed=12))
    b.forecast(N, "SKU-1002", per_day=40)
    b.po("PO-1101", "SUP-METRO", N, "SKU-1002", 200, 1.50, status="CONFIRMED", confirmed=200, arrives_in=3)
    b.budget("Snacks", amount=5000, spent=3200)
    b.recommendation("REC-1002", N, "SKU-1002", "SUP-METRO", 800,
                     reason="Target 20 days of cover at forecast 40/day = 800 units.")


@scenario(
    id="S1-ACCEPT", group=1,
    title="Recommendation is correct",
    situation="The replenishment engine recommends buying 480 units of Sparkling Water 1L (SKU-1001) "
              "from Metro Wholesale for Dark Store North. Review the recommendation.",
    summary="The engine wants 480 bottles of sparkling water. The math, budget and storage all check out, so the order should go ahead as is.",
    trigger={"type": "RECOMMENDATION_REVIEW", "rec_id": "REC-1001"},
    expected=Expected(
        decision=ACCEPT,
        required_info=("inventory", "forecast", "open_pos", "suppliers", "storage", "budget"),
        new_buy_qty=(456, 504),
        allowed_suppliers=("SUP-METRO",),
        worked_example=(
            "target = 50/day x 15 days = 750. position = 270 on hand + 0 inbound. net need = 480 = 20 cases "
            "of 24 exactly, above MOQ 240. Cost $960 vs $6,000 budget left; storage has 1,730 free. "
            "270 on hand lasts 5.4 days, so the order (5-day lead) arrives before a stockout."
        ),
    ),
)
def _s1_accept(b: Builder) -> None:
    base_world(b)
    b.product("SKU-1001", "Sparkling Water 1L", "Beverages", case_pack=24)
    b.offer("SUP-METRO", "SKU-1001", cost=2.00, moq=240, lead=5, primary=True)
    b.stock(N, "SKU-1001", on_hand=270)
    b.sales(N, "SKU-1001", steady(50, 28, seed=11))
    b.forecast(N, "SKU-1001", per_day=50)
    b.budget("Beverages", amount=10000, spent=4000)
    b.recommendation("REC-1001", N, "SKU-1001", "SUP-METRO", 480,
                     reason="Order-up-to 15 days of cover at forecast 50/day, net of 270 on hand and 0 inbound.")


@scenario(
    id="S1-REJECT", group=1,
    title="Already overstocked - standing order should not fire",
    situation="The replenishment engine recommends buying 480 units of Instant Noodles 70g (SKU-1003) "
              "from Metro Wholesale for Dark Store North. Review the recommendation.",
    summary="A standing order for 480 noodles fired even though the store already has 35 days of stock. Nothing should be bought.",
    trigger={"type": "RECOMMENDATION_REVIEW", "rec_id": "REC-1003"},
    expected=Expected(
        decision=REJECT,
        required_info=("inventory", "forecast", "open_pos"),
        new_buy_qty=(0, 0),
        worked_example=(
            "target = 20/day x 15 days = 300. position = 500 on hand + 200 inbound = 700 (35 days of cover). "
            "net need = 0. The engine fired a fixed standing order (10 cases, exactly the MOQ) regardless of stock; "
            "buying it would push cover to ~59 days."
        ),
    ),
)
def _s1_reject(b: Builder) -> None:
    base_world(b)
    b.product("SKU-1003", "Instant Noodles Masala 70g", "Pantry", case_pack=48)
    b.offer("SUP-METRO", "SKU-1003", cost=0.40, moq=480, lead=5, primary=True)
    b.stock(N, "SKU-1003", on_hand=500)
    b.sales(N, "SKU-1003", steady(20, 28, seed=13))
    b.forecast(N, "SKU-1003", per_day=20)
    b.po("PO-1301", "SUP-METRO", N, "SKU-1003", 200, 0.40, status="CONFIRMED", confirmed=200, arrives_in=2)
    b.budget("Pantry", amount=20000, spent=9000)
    b.recommendation("REC-1003", N, "SKU-1003", "SUP-METRO", 480,
                     reason="Standing weekly order: 480 units (10 cases) every Monday.")


@scenario(
    id="S1-INVESTIGATE", group=1,
    title="Inventory record contradicts recent receipts and sales",
    situation="The replenishment engine recommends buying 800 units of Peanut Butter 340g (SKU-1004) "
              "from Metro Wholesale for Dark Store North. Review the recommendation.",
    summary="The system says peanut butter stock is 0, but 400 units arrived 2 days ago and sales continued. The record is probably wrong, so count before buying 800.",
    trigger={"type": "RECOMMENDATION_REVIEW", "rec_id": "REC-1004"},
    expected=Expected(
        decision=INVESTIGATE,
        required_info=("inventory", "sales_history", "open_pos"),
        new_buy_qty=(0, 0),
        escalation="INVESTIGATION",
        worked_example=(
            "System says on_hand = 0 (last counted 9 days ago), yet PO-1401 delivered 400 units 2 days ago "
            "and the store kept selling ~45/day since. Expected stock is ~300+, not 0. Ordering 800 on a "
            "record that is probably wrong risks heavy overstock -> request a cycle count first."
        ),
    ),
)
def _s1_investigate(b: Builder) -> None:
    base_world(b)
    b.product("SKU-1004", "Peanut Butter Creamy 340g", "Pantry", case_pack=12)
    b.offer("SUP-METRO", "SKU-1004", cost=3.20, moq=120, lead=5, primary=True)
    b.stock(N, "SKU-1004", on_hand=0, counted_days_ago=9)
    b.sales(N, "SKU-1004", steady(40, 25, seed=14) + [44, 45, 46])
    b.forecast(N, "SKU-1004", per_day=40)
    b.po("PO-1401", "SUP-METRO", N, "SKU-1004", 400, 3.20, status="RECEIVED", confirmed=400,
         arrives_in=-2, created_days_ago=8)
    b.budget("Pantry", amount=20000, spent=9000)
    b.recommendation("REC-1004", N, "SKU-1004", "SUP-METRO", 800,
                     reason="On-hand is 0 - emergency replenishment to 20 days of cover (20 x 40).")


# ===========================================================================
# SCENARIO 2 - Supplier cannot fulfil the purchase (500 ordered, 250 confirmed)
# Shared supplier menu: the "obvious" cheap options are traps.
# ===========================================================================
def _s2_supplier_menu(b: Builder, sku: str, *, quick_live: int | None = None) -> None:
    b.offer("SUP-METRO",  sku, cost=8.00, moq=100, lead=6, primary=True, live_available=0)  # cannot supply more
    b.offer("SUP-QUICK",  sku, cost=8.60, moq=50,  lead=3, listed_capacity=1000, live_available=quick_live)
    b.offer("SUP-RAPIDO", sku, cost=8.90, moq=20,  lead=4, listed_capacity=800)
    b.offer("SUP-BULK",   sku, cost=7.50, moq=200, lead=12)                  # cheap but slow + unreliable
    b.offer("SUP-SHADY",  sku, cost=6.90, moq=50,  lead=3)                   # cheapest but NOT approved


def _s2_short_po(b: Builder, po: str, sku: str) -> None:
    b.po(po, "SUP-METRO", N, sku, 500, 8.00, status="PARTIALLY_CONFIRMED", confirmed=250, arrives_in=3)
    b.supplier_event(f"EVT-{po}", po, "SUP-METRO", "PARTIAL_CONFIRMATION",
                     {"qty_ordered": 500, "qty_confirmed": 250,
                      "message": "Mill shortage. We can ship 250 units on the original date; "
                                 "the remaining 250 are not available for at least 3 weeks."})


@scenario(
    id="S2-SOURCE-ELSEWHERE", group=2,
    title="Short shipment leaves a gap - source the remainder from an alternate",
    situation="Metro Wholesale can only supply 250 of the 500 units on PO-2001 (Basmati Rice 5kg, "
              "SKU-2001, Dark Store North). Decide what should happen next.",
    summary="Metro can only ship 250 of 500 bags of rice, which leaves a gap before the next delivery. Buy the rest from a fast, approved supplier, avoiding the cheap unapproved and slow ones.",
    trigger={"type": "SUPPLIER_EVENT", "event_id": "EVT-PO-2001"},
    expected=Expected(
        decision=MODIFY,
        required_info=("supplier_events", "inventory", "forecast", "open_pos", "suppliers", "budget"),
        new_buy_qty=(90, 220),
        allowed_suppliers=("SUP-QUICK", "SUP-RAPIDO"),
        worked_example=(
            "With only 250 inbound: position = 180 + 250 = 430. Need at 40/day x (lead + 7 review + 3 safety): "
            "QuickSupply (3-day lead) 90, Rapido (4-day) 130, Metro (6-day) 210. Buy ~90-210 from an approved, "
            "fast supplier (QuickSupply, MOQ 50, 3 days). Traps: Unverified Imports is cheapest but NOT "
            "approved; BulkBuy is cheap but its 12-day lead lands after the projected day-10 stockout, "
            "72% on-time, MOQ 200; Metro has no more stock."
        ),
    ),
)
def _s2_source(b: Builder) -> None:
    base_world(b)
    b.product("SKU-2001", "Basmati Rice 5kg", "Pantry", case_pack=10)
    _s2_supplier_menu(b, "SKU-2001")
    b.stock(N, "SKU-2001", on_hand=180)
    b.sales(N, "SKU-2001", steady(40, 28, seed=21))
    b.forecast(N, "SKU-2001", per_day=40)
    _s2_short_po(b, "PO-2001", "SKU-2001")
    b.budget("Pantry", amount=20000, spent=9000)


@scenario(
    id="S2-ACCEPT-SHORT", group=2,
    title="Short shipment, but existing stock already covers demand",
    situation="Metro Wholesale can only supply 250 of the 500 units on PO-2002 (Sunflower Oil 1L, "
              "SKU-2002, Dark Store North). Decide what should happen next.",
    summary="Metro can only ship 250 of 500 bottles of sunflower oil, but stock on hand already covers over a month. Accept the short shipment.",
    trigger={"type": "SUPPLIER_EVENT", "event_id": "EVT-PO-2002"},
    expected=Expected(
        decision=ACCEPT,
        required_info=("supplier_events", "inventory", "forecast", "open_pos"),
        new_buy_qty=(0, 0),
        worked_example=(
            "target at 15/day = 15 x 16 = 240. position = 300 on hand + 250 confirmed = 550 (~37 days). "
            "Accept the partial confirmation, no replacement PO needed."
        ),
    ),
)
def _s2_accept(b: Builder) -> None:
    base_world(b)
    b.product("SKU-2002", "Sunflower Oil 1L", "Pantry", case_pack=12)
    _s2_supplier_menu(b, "SKU-2002")
    b.stock(N, "SKU-2002", on_hand=300)
    b.sales(N, "SKU-2002", steady(15, 28, seed=22))
    b.forecast(N, "SKU-2002", per_day=15)
    _s2_short_po(b, "PO-2002", "SKU-2002")
    b.budget("Pantry", amount=20000, spent=9000)


@scenario(
    id="S2-ALT-ALSO-SHORT", group=2,
    title="Alternate supplier ALSO short-confirms - agent must recover",
    situation="Metro Wholesale can only supply 250 of the 500 units on PO-2003 (Whole Wheat Flour 5kg, "
              "SKU-2003, Dark Store North). Decide what should happen next.",
    summary="Metro ships only 250 of 500 bags of flour, and the alternate supplier then also confirms less than ordered. The agent must notice and source the rest elsewhere or escalate.",
    trigger={"type": "SUPPLIER_EVENT", "event_id": "EVT-PO-2003"},
    expected=Expected(
        decision=MODIFY,
        required_info=("supplier_events", "inventory", "forecast", "open_pos", "suppliers", "budget"),
        new_buy_qty=(90, 220),
        allowed_suppliers=("SUP-QUICK", "SUP-RAPIDO"),
        worked_example=(
            "Same gap as S2-SOURCE-ELSEWHERE (position 430, need 90 from QuickSupply). Catalog says QuickSupply "
            "has 1,000 units, but when the PO is submitted they only confirm 40, which is always short. The "
            "validation step must catch the shortfall and source the rest from Rapido (MOQ 20, 4 days) "
            "- or escalate."
        ),
    ),
)
def _s2_alt_short(b: Builder) -> None:
    base_world(b)
    b.product("SKU-2003", "Whole Wheat Flour 5kg", "Pantry", case_pack=10)
    _s2_supplier_menu(b, "SKU-2003", quick_live=40)
    b.stock(N, "SKU-2003", on_hand=180)
    b.sales(N, "SKU-2003", steady(40, 28, seed=23))
    b.forecast(N, "SKU-2003", per_day=40)
    _s2_short_po(b, "PO-2003", "SKU-2003")
    b.budget("Pantry", amount=20000, spent=9000)


# ===========================================================================
# SCENARIO 3 - Demand / forecast has changed
# The trigger is a naive monitoring alert ("7-day sales >> forecast"). The agent
# must decide whether the spike is real, a one-off, or explained by a promo.
# ===========================================================================
@scenario(
    id="S3-SUSTAINED-SPIKE", group=3,
    title="Sustained demand increase - open PO no longer enough",
    situation="Demand alert: 7-day average sales of Electrolyte Drink 500ml (SKU-3001) at Dark Store North "
              "are ~2.5x the forecast. PO-3001 is open. Check whether the purchasing plan needs to change.",
    summary="Electrolyte drink sales have been climbing for a week to about 2.5x the forecast. The open PO is no longer enough, so order about 420 more.",
    trigger={"type": "DEMAND_ALERT", "node_id": N, "sku": "SKU-3001"},
    expected=Expected(
        decision=MODIFY,
        required_info=("sales_history", "forecast", "inventory", "open_pos", "promotions", "suppliers"),
        new_buy_qty=(180, 650),
        allowed_suppliers=("SUP-METRO", "SUP-QUICK"),
        worked_example=(
            "Last 7 days: 62,68,71,77,80,78,84 (avg ~74, rising trend with one small dip, no promo) vs forecast 30. "
            "At ~74/day: target = 74 x 15 = ~1,115. position = 400 + 300 (PO-3001) = 700. Gap ~415 -> "
            "~420 units (35 cases). Stock lasts ~5.4 days and PO-3001 lands in 4, so no stockout before it."
        ),
    ),
)
def _s3_spike(b: Builder) -> None:
    base_world(b)
    b.product("SKU-3001", "Electrolyte Drink 500ml", "Beverages", case_pack=12)
    b.offer("SUP-METRO", "SKU-3001", cost=1.10, moq=120, lead=5, primary=True)
    b.offer("SUP-QUICK", "SKU-3001", cost=1.25, moq=48, lead=2)
    b.stock(N, "SKU-3001", on_hand=400)
    b.sales(N, "SKU-3001", steady(30, 21, seed=31) + [62, 68, 71, 77, 80, 78, 84])
    b.forecast(N, "SKU-3001", per_day=30)
    b.po("PO-3001", "SUP-METRO", N, "SKU-3001", 300, 1.10, status="SUBMITTED", arrives_in=4)
    b.budget("Beverages", amount=10000, spent=4000)


@scenario(
    id="S3-PROMO-ENDING", group=3,
    title="Spike is explained by a promotion that ends tomorrow",
    situation="Demand alert: 7-day average sales of Energy Drink 250ml (SKU-3003) at Dark Store North are "
              "~2.9x the forecast. PO-3003 is open. Check whether the purchasing plan needs to change.",
    summary="Energy drink sales are 2.9x the forecast because of a promotion that ends tomorrow. Stock covers the last promo days, so change nothing.",
    trigger={"type": "DEMAND_ALERT", "node_id": N, "sku": "SKU-3003"},
    expected=Expected(
        decision=ACCEPT,
        required_info=("sales_history", "forecast", "promotions", "inventory", "open_pos"),
        new_buy_qty=(0, 0),
        worked_example=(
            "Sales jumped to ~70/day exactly when PROMO-77 (buy 2 get 1) started; it ends tomorrow. "
            "Sales ran ~73/day, ~2.9x the forecast of 25. Next 2 promo days need ~146 (have 420). After that, "
            "back to 25/day: target 375 vs position ~274 + 200 = ~474 -> no change."
        ),
    ),
)
def _s3_promo(b: Builder) -> None:
    base_world(b)
    b.product("SKU-3003", "Energy Drink 250ml", "Beverages", case_pack=24)
    b.offer("SUP-METRO", "SKU-3003", cost=0.90, moq=96, lead=5, primary=True)
    b.stock(N, "SKU-3003", on_hand=420)
    b.sales(N, "SKU-3003", steady(25, 21, seed=33) + steady(70, 7, seed=34))
    b.forecast(N, "SKU-3003", per_day=25)
    b.promo("PROMO-77", N, "SKU-3003", start=-7, end=1, description="Buy 2 get 1 free - app homepage banner")
    b.po("PO-3003", "SUP-METRO", N, "SKU-3003", 200, 0.90, status="SUBMITTED", arrives_in=3)
    b.budget("Beverages", amount=10000, spent=4000)


# ===========================================================================
# SCENARIO 4 - Purchasing constraint blocks the recommended purchase
# ===========================================================================
@scenario(
    id="S4-BUDGET", group=4,
    title="Need is real but exceeds the remaining category budget",
    situation="The replenishment engine recommends buying 576 units of Extra Virgin Olive Oil 1L (SKU-4001) "
              "from Metro Wholesale for Dark Store North. Review and act.",
    summary="Olive oil really needs 576 units, but the category budget only covers 396. Buy 396 and ask for a budget increase for the rest.",
    trigger={"type": "RECOMMENDATION_REVIEW", "rec_id": "REC-4001"},
    expected=Expected(
        decision=MODIFY,
        required_info=("inventory", "forecast", "open_pos", "suppliers", "budget"),
        new_buy_qty=(120, 396),
        allowed_suppliers=("SUP-METRO",),
        escalation="BUDGET_INCREASE",
        worked_example=(
            "target = 60/day x (7+7+3) = 1,020. position = 450. need = 570 -> 576 (48 cases) = $3,456. "
            "Pantry budget left = $2,400 -> max 396 units (33 cases, $2,376). Buy 396 now so the shelf "
            "doesn't run dry, and escalate a budget increase of ~$1,080 for the other 180."
        ),
    ),
)
def _s4_budget(b: Builder) -> None:
    base_world(b)
    b.product("SKU-4001", "Extra Virgin Olive Oil 1L", "Pantry", case_pack=12)
    b.offer("SUP-METRO", "SKU-4001", cost=6.00, moq=120, lead=7, primary=True)
    b.stock(N, "SKU-4001", on_hand=450)
    b.sales(N, "SKU-4001", steady(60, 28, seed=41))
    b.forecast(N, "SKU-4001", per_day=60)
    b.budget("Pantry", amount=20000, spent=17600)
    b.recommendation("REC-4001", N, "SKU-4001", "SUP-METRO", 576,
                     reason="Order-up-to 17 days of cover at 60/day, net of 450 on hand.")


@scenario(
    id="S4-MOQ-VS-SHELF-LIFE", group=4,
    title="Primary supplier's MOQ would force buying more than can sell before expiry",
    situation="The replenishment engine recommends buying 180 units of Fresh Paneer 200g (SKU-4002) from "
              "DairyDirect for Dark Store North. Review and act.",
    summary="Paneer needs 42 units, but DairyDirect's minimum order is 180 and paneer expires in 10 days. Buy 42 from FarmFresh at a slightly higher price instead.",
    trigger={"type": "RECOMMENDATION_REVIEW", "rec_id": "REC-4002"},
    expected=Expected(
        decision=MODIFY,
        required_info=("inventory", "forecast", "suppliers"),
        new_buy_qty=(36, 72),
        allowed_suppliers=("SUP-FARM",),
        worked_example=(
            "Perishable, 10-day shelf life. target = 12/day x (2+3+1) = 72; on hand 30 -> need 42 (7 cases of 6). "
            "DairyDirect MOQ is 180 (30 cases) -> 30 + 180 = 210 units = 17.5 days of cover vs a 10-day shelf life, "
            "so ~66 units would expire (~$165). FarmFresh: MOQ 30, +$0.40/unit, same 2-day lead -> buy 42 there. "
            "Paying 16% more on 42 units ($16.80) beats writing off ~66 units ($165)."
        ),
    ),
)
def _s4_moq(b: Builder) -> None:
    base_world(b)
    b.product("SKU-4002", "Fresh Paneer 200g", "Dairy", zone="chilled", case_pack=6,
              shelf_life=10, review=3, safety=1)
    b.offer("SUP-DAIRY", "SKU-4002", cost=2.50, moq=180, lead=2, primary=True)
    b.offer("SUP-FARM",  "SKU-4002", cost=2.90, moq=30,  lead=2)
    b.stock(N, "SKU-4002", on_hand=30)
    b.sales(N, "SKU-4002", steady(12, 28, seed=42))
    b.forecast(N, "SKU-4002", per_day=12)
    b.budget("Dairy", amount=4000, spent=1500)
    b.recommendation("REC-4002", N, "SKU-4002", "SUP-DAIRY", 180,
                     reason="Net need 42 units, rounded up to supplier MOQ (180).")
