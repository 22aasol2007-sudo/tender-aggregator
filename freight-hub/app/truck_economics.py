"""Unit economics for one specific truck (Moscow corridor)."""

from __future__ import annotations

import math
from typing import Any

from app import config


def _f(name: str, default: float) -> float:
    try:
        return float(getattr(config, name, default) or default)
    except (TypeError, ValueError):
        return float(default)


def truck_params() -> dict[str, float]:
    return {
        "load_unload_hours": _f("TRUCK_LOAD_UNLOAD_HOURS", 2.5),
        "driver_day_rub": _f("TRUCK_DRIVER_DAY_RUB", 10000),
        "fuel_l_per_100km": _f("TRUCK_FUEL_L_PER_100KM", 30),
        "diesel_rub_per_l": _f("TRUCK_DIESEL_RUB_PER_L", 80),
        "amortization_pct": _f("TRUCK_AMORTIZATION_PCT", 0.05),
        "tax_pct": _f("TRUCK_TAX_PCT", 0.35),
        "target_net_min": _f("TRUCK_TARGET_NET_MIN", 10000),
        "target_net_max": _f("TRUCK_TARGET_NET_MAX", 15000),
        "avg_speed_kmh": _f("TRUCK_AVG_SPEED_KMH", 55),
        "backhaul_radius_km": _f("BACKHAUL_RADIUS_KM", 100),
    }


def fuel_rub_for_km(km: float, p: dict[str, float] | None = None) -> float:
    p = p or truck_params()
    return float(km) / 100.0 * p["fuel_l_per_100km"] * p["diesel_rub_per_l"]


def trip_hours(*, km_one_way: float, with_backhaul: bool, p: dict[str, float] | None = None) -> float:
    """Drive round-trip + handling. Backhaul adds another load/unload cycle."""
    p = p or truck_params()
    speed = max(30.0, p["avg_speed_kmh"])
    drive = 2.0 * float(km_one_way) / speed
    handling = p["load_unload_hours"] * (2.0 if with_backhaul else 1.0)
    return drive + handling


def trip_days(hours: float) -> int:
    """Calendar-ish days for driver pay (ceil of 24h blocks, min 1)."""
    if hours <= 0:
        return 1
    return max(1, int(math.ceil(hours / 24.0)))


def revenue_for_target_net(*, costs: float, target_net: float, p: dict[str, float] | None = None) -> float:
    """
    Tax is taken from the client rate (turnover), not from profit:

      tax = tax_pct * R
      amort = amortization_pct * R
      net = R - tax - amort - costs
          = R * (1 - tax_pct - amortization_pct) - costs

    Solve for target net:
      R = (costs + target_net) / (1 - tax_pct - amortization_pct)
    """
    p = p or truck_params()
    amort = min(0.4, max(0.0, p["amortization_pct"]))
    tax = min(0.9, max(0.0, p["tax_pct"]))
    keep = max(0.05, 1.0 - tax - amort)
    return (float(costs) + float(target_net)) / keep


def net_profit(*, revenue: float, costs: float, p: dict[str, float] | None = None) -> float:
    """Net after tax-on-rate, amortization-on-rate, and operating costs."""
    p = p or truck_params()
    r = float(revenue)
    tax = r * p["tax_pct"]
    amort = r * p["amortization_pct"]
    return r - tax - amort - float(costs)


def price_outbound_leg(
    *,
    km: float,
    p_find_backhaul: float,
    p: dict[str, float] | None = None,
) -> dict[str, Any]:
    """
    Minimum outbound rate so that expected net profit hits target band.
    Tax 35% and amortization 5% are taken from the client rate; then operating costs.
    """
    p = p or truck_params()
    km = float(km or 0)
    if km <= 0:
        return {"ok": False, "error": "Нет километража маршрута"}

    pf = max(0.0, min(1.0, float(p_find_backhaul)))
    fuel_one = fuel_rub_for_km(km, p)
    fuel_round = fuel_one * 2.0

    hours_empty = trip_hours(km_one_way=km, with_backhaul=False, p=p)
    hours_bh = trip_hours(km_one_way=km, with_backhaul=True, p=p)
    days_empty = trip_days(hours_empty)
    days_bh = trip_days(hours_bh)

    driver_empty = days_empty * p["driver_day_rub"]
    driver_bh = days_bh * p["driver_day_rub"]

    # If backhaul found: return fuel/driver attributed to other load → outbound bears outbound fuel + half driver days of round
    # Conservative EV: outbound must cover full empty-return costs with probability (1-p)
    costs_if_empty = fuel_round + driver_empty
    costs_if_bh = fuel_one + driver_empty * 0.55  # outbound share when return is paid by backhaul
    expected_costs = (1.0 - pf) * costs_if_empty + pf * costs_if_bh

    r_min = revenue_for_target_net(costs=expected_costs, target_net=p["target_net_min"], p=p)
    r_mid = revenue_for_target_net(
        costs=expected_costs,
        target_net=(p["target_net_min"] + p["target_net_max"]) / 2.0,
        p=p,
    )
    r_max = revenue_for_target_net(costs=expected_costs, target_net=p["target_net_max"], p=p)

    # Worst-case quote (assume empty return for sure)
    r_empty_min = revenue_for_target_net(costs=costs_if_empty, target_net=p["target_net_min"], p=p)

    return {
        "ok": True,
        "params": p,
        "km": round(km, 1),
        "p_find": round(pf, 2),
        "hours_empty_return": round(hours_empty, 1),
        "hours_with_backhaul": round(hours_bh, 1),
        "days_empty_return": days_empty,
        "days_with_backhaul": days_bh,
        "fuel_one_way_rub": round(fuel_one, 0),
        "fuel_round_rub": round(fuel_round, 0),
        "driver_empty_rub": round(driver_empty, 0),
        "driver_backhaul_rub": round(driver_bh, 0),
        "costs_if_empty_rub": round(costs_if_empty, 0),
        "costs_if_backhaul_rub": round(costs_if_bh, 0),
        "expected_costs_rub": round(expected_costs, 0),
        "suggested_min_total_rub": round(r_min, 0),
        "suggested_mid_total_rub": round(r_mid, 0),
        "suggested_max_total_rub": round(r_max, 0),
        "suggested_empty_safe_rub": round(r_empty_min, 0),
        "suggested_min_ppk": round(r_min / km, 1),
        "suggested_mid_ppk": round(r_mid / km, 1),
        "suggested_max_ppk": round(r_max / km, 1),
        "amortization_pct": p["amortization_pct"],
        "tax_pct": p["tax_pct"],
        "tax_on": "client_rate",
        "target_net_min": p["target_net_min"],
        "target_net_max": p["target_net_max"],
    }


def evaluate_offer(
    *,
    offer_rub: float,
    km: float,
    p_find_backhaul: float,
    p: dict[str, float] | None = None,
) -> dict[str, Any]:
    priced = price_outbound_leg(km=km, p_find_backhaul=p_find_backhaul, p=p)
    if not priced.get("ok"):
        return priced
    p = priced["params"]
    costs = float(priced["expected_costs_rub"])
    net = net_profit(revenue=float(offer_rub), costs=costs, p=p)
    hurdle = float(priced["suggested_min_total_rub"])
    return {
        "offer_rub": float(offer_rub),
        "offer_ppk": round(float(offer_rub) / float(km), 1) if km else None,
        "expected_net_rub": round(net, 0),
        "vs_hurdle_rub": round(float(offer_rub) - hurdle, 0),
        "verdict": (
            "выгодно"
            if net >= p["target_net_min"]
            else ("на грани" if net >= p["target_net_min"] * 0.7 else "риск минуса")
        ),
        "in_target_band": p["target_net_min"] <= net <= p["target_net_max"],
    }
