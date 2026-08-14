"""Unit economics tests for one-truck pricing."""

from app.truck_economics import evaluate_offer, net_profit, price_outbound_leg, revenue_for_target_net


def test_fuel_and_revenue_solve():
    # 174 km one way → fuel round = 2 * 174/100 * 30 * 80 = 8352
    priced = price_outbound_leg(km=174, p_find_backhaul=0.2)
    assert priced["ok"]
    assert priced["fuel_round_rub"] == 8352
    assert priced["fuel_one_way_rub"] == 4176
    assert priced["suggested_min_total_rub"] > priced["expected_costs_rub"]
    assert priced["suggested_max_total_rub"] >= priced["suggested_min_total_rub"]
    # Empty-safe quote higher than EV quote when p_find > 0
    assert priced["suggested_empty_safe_rub"] >= priced["suggested_min_total_rub"]


def test_backhaul_costs_use_outbound_leg_not_magic_factor():
    priced = price_outbound_leg(km=200, p_find_backhaul=0.5)
    assert priced["ok"]
    # С обраткой: топливо в одну сторону + водитель на плечо «туда»
    assert priced["costs_if_backhaul_rub"] == priced["fuel_one_way_rub"] + priced["driver_outbound_rub"]
    # Порожняк дороже обратки
    assert priced["costs_if_empty_rub"] > priced["costs_if_backhaul_rub"]
    # Риск порожняка = (1-p) * разница сценариев
    gap = priced["costs_if_empty_rub"] - priced["costs_if_backhaul_rub"]
    assert abs(priced["empty_risk_rub"] - round(0.5 * gap, 0)) <= 1.0
    # Ожидаемые затраты — смесь сценариев
    exp = 0.5 * priced["costs_if_empty_rub"] + 0.5 * priced["costs_if_backhaul_rub"]
    assert abs(priced["expected_costs_rub"] - round(exp, 0)) <= 1.0


def test_net_tax_from_client_rate():
    # R=100000 → tax 35000 + amort 5000 + costs 40000 → net 20000
    assert round(net_profit(revenue=100000, costs=40000)) == 20000


def test_revenue_inverse():
    costs = 20000
    target = 10000
    r = revenue_for_target_net(costs=costs, target_net=target)
    # keep share = 1 - 0.35 - 0.05 = 0.60 → R = (20000+10000)/0.60 = 50000
    assert abs(r - 50000) < 1.0
    assert abs(net_profit(revenue=r, costs=costs) - target) < 1.0


def test_offer_verdict():
    priced = price_outbound_leg(km=200, p_find_backhaul=0.1)
    low = evaluate_offer(offer_rub=1000, km=200, p_find_backhaul=0.1)
    high = evaluate_offer(
        offer_rub=float(priced["suggested_max_total_rub"]) + 5000,
        km=200,
        p_find_backhaul=0.1,
    )
    assert low["verdict"] == "риск минуса"
    assert high["verdict"] == "выгодно"


def test_waterfall_and_scenarios():
    priced = price_outbound_leg(km=200, p_find_backhaul=0.4)
    assert priced["ok"]
    assert "waterfall" in priced
    keys = [s["key"] for s in priced["waterfall"]["steps"]]
    assert keys == ["rate", "tax", "amort", "fuel", "driver", "empty_risk", "net"]
    assert "with_backhaul" in priced["scenarios"]
    assert "empty_return" in priced["scenarios"]
    assert priced["scenarios"]["empty_return"]["suggest_min_rub"] >= priced["scenarios"]["with_backhaul"]["suggest_min_rub"]


def test_build_verdict_actions():
    from app.truck_economics import build_verdict, truck_params

    p = truck_params()
    v = build_verdict(offer_rub=None, suggested_min=50000, empty_safe=70000, p_find=0.5, p=p)
    assert v["action"] == "propose"
    assert v["propose_rub"] == 50000
    take = build_verdict(offer_rub=60000, suggested_min=50000, empty_safe=70000, p_find=0.5, p=p)
    assert take["action"] == "take"
    raise_ = build_verdict(offer_rub=40000, suggested_min=50000, empty_safe=70000, p_find=0.5, p=p)
    assert raise_["action"] == "raise"


def test_params_override():
    from app.truck_economics import truck_params

    p = truck_params({"diesel_rub_per_l": 90, "tax_pct": 0.3})
    assert p["diesel_rub_per_l"] == 90
    assert p["tax_pct"] == 0.3

