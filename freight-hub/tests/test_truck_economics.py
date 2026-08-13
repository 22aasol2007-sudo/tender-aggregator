"""Unit economics tests for one-truck pricing."""

from app.truck_economics import evaluate_offer, net_profit, price_outbound_leg, revenue_for_target_net


def test_fuel_and_revenue_solve():
    # 174 km one way → fuel round = 2 * 174/100 * 30 * 80 = 8352
    priced = price_outbound_leg(km=174, p_find_backhaul=0.2)
    assert priced["ok"]
    assert priced["fuel_round_rub"] == 8352
    assert priced["suggested_min_total_rub"] > priced["expected_costs_rub"]
    assert priced["suggested_max_total_rub"] >= priced["suggested_min_total_rub"]
    # Empty-safe quote higher than EV quote when p_find > 0
    assert priced["suggested_empty_safe_rub"] >= priced["suggested_min_total_rub"]


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
