"""Phase 1 sanity checks: every scenario builds, and its data matches its story."""
import pytest

from app.scenarios.catalog import SCENARIOS
from app.scenarios.seed import build_scenario_db
from app.scenarios.types import INFO_CATEGORIES


@pytest.mark.parametrize("sid", list(SCENARIOS))
def test_scenario_builds(sid):
    conn = build_scenario_db(sid, ":memory:")
    assert conn.execute("SELECT COUNT(*) FROM products").fetchone()[0] >= 1
    assert conn.execute("SELECT COUNT(*) FROM forecasts").fetchone()[0] > 0


@pytest.mark.parametrize("sid", list(SCENARIOS))
def test_trigger_points_at_real_data(sid):
    s = SCENARIOS[sid]
    conn = build_scenario_db(sid, ":memory:")
    t = s.trigger
    if t["type"] == "RECOMMENDATION_REVIEW":
        assert conn.execute("SELECT 1 FROM recommendations WHERE rec_id=?", (t["rec_id"],)).fetchone()
    elif t["type"] == "SUPPLIER_EVENT":
        assert conn.execute("SELECT 1 FROM supplier_events WHERE event_id=?", (t["event_id"],)).fetchone()
    elif t["type"] == "DEMAND_ALERT":
        assert conn.execute("SELECT 1 FROM inventory WHERE sku=?", (t["sku"],)).fetchone()
    else:
        pytest.fail(f"unknown trigger {t['type']}")


def test_every_assignment_scenario_has_a_do_nothing_variant():
    """Guard against an agent that always acts: each group needs a case where buying is wrong."""
    for group in (1, 2, 3):
        assert any(s.group == group and s.expected.new_buy_qty == (0, 0) for s in SCENARIOS.values()), group


def test_hidden_supplier_shortfall_in_recovery_scenario():
    conn = build_scenario_db("S2-ALT-ALSO-SHORT", ":memory:")
    listed = conn.execute("SELECT listed_capacity_units FROM supplier_products "
                          "WHERE supplier_id='SUP-QUICK' AND sku='SKU-2003'").fetchone()[0]
    live = conn.execute("SELECT available_units FROM supplier_live_availability "
                        "WHERE supplier_id='SUP-QUICK' AND sku='SKU-2003'").fetchone()[0]
    assert (listed, live) == (1000, 40)


@pytest.mark.parametrize("sid", list(SCENARIOS))
def test_allowed_suppliers_are_approved_and_sell_the_sku(sid):
    conn = build_scenario_db(sid, ":memory:")
    skus = [r[0] for r in conn.execute("SELECT sku FROM products")]
    for supplier in SCENARIOS[sid].expected.allowed_suppliers or ():
        approved = conn.execute("SELECT is_approved FROM suppliers WHERE supplier_id=?", (supplier,)).fetchone()
        assert approved and approved[0] == 1, supplier
        for sku in skus:
            assert conn.execute("SELECT 1 FROM supplier_products WHERE supplier_id=? AND sku=?",
                                (supplier, sku)).fetchone(), (supplier, sku)


# The engine's recommendation is deliberately wrong in these (raw 20 days x 40, not rounded to the case
# pack), so they are the only ones allowed to break pack/MOQ rules. S1-REJECT's standing order is a
# valid PO on its own: the only reason to reject it is that the store is already overstocked.
WRONG_BY_DESIGN = {"S1-MODIFY", "S1-INVESTIGATE"}


@pytest.mark.parametrize("sid", [s for s in SCENARIOS if s not in WRONG_BY_DESIGN])
def test_recommendation_qty_respects_case_pack_and_moq(sid):
    conn = build_scenario_db(sid, ":memory:")
    for qty, case_pack, moq in conn.execute(
            "SELECT r.recommended_qty, p.case_pack, sp.moq FROM recommendations r "
            "JOIN products p ON p.sku = r.sku "
            "JOIN supplier_products sp ON sp.sku = r.sku AND sp.supplier_id = r.supplier_id"):
        assert qty % case_pack == 0 and qty >= moq, (qty, case_pack, moq)


@pytest.mark.parametrize("sid", list(SCENARIOS))
def test_required_info_uses_the_shared_vocabulary(sid):
    assert set(SCENARIOS[sid].expected.required_info) <= INFO_CATEGORIES


@pytest.mark.parametrize("sid", ["S2-SOURCE-ELSEWHERE", "S2-ACCEPT-SHORT", "S2-ALT-ALSO-SHORT"])
def test_s2_metro_has_no_more_stock(sid):
    """The event says Metro can't supply the rest, so its hidden live availability must be 0."""
    conn = build_scenario_db(sid, ":memory:")
    live = conn.execute("SELECT available_units FROM supplier_live_availability "
                        "WHERE supplier_id='SUP-METRO'").fetchone()[0]
    assert live == 0
