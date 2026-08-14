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


def truck_params(overrides: dict[str, Any] | None = None) -> dict[str, float]:
    p = {
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
    if overrides:
        for k, v in overrides.items():
            if k in p and v is not None and v != "":
                try:
                    p[k] = float(v)
                except (TypeError, ValueError):
                    pass
    return p


def fuel_rub_for_km(km: float, p: dict[str, float] | None = None) -> float:
    p = p or truck_params()
    return float(km) / 100.0 * p["fuel_l_per_100km"] * p["diesel_rub_per_l"]


def trip_hours(*, km_one_way: float, with_backhaul: bool, p: dict[str, float] | None = None) -> float:
    p = p or truck_params()
    speed = max(30.0, p["avg_speed_kmh"])
    drive = 2.0 * float(km_one_way) / speed
    handling = p["load_unload_hours"] * (2.0 if with_backhaul else 1.0)
    return drive + handling


def trip_days(hours: float) -> int:
    if hours <= 0:
        return 1
    return max(1, int(math.ceil(hours / 24.0)))


def revenue_for_target_net(*, costs: float, target_net: float, p: dict[str, float] | None = None) -> float:
    """R = (costs + target) / (1 - tax - amort); tax & amort from client rate."""
    p = p or truck_params()
    amort = min(0.4, max(0.0, p["amortization_pct"]))
    tax = min(0.9, max(0.0, p["tax_pct"]))
    keep = max(0.05, 1.0 - tax - amort)
    return (float(costs) + float(target_net)) / keep


def net_profit(*, revenue: float, costs: float, p: dict[str, float] | None = None) -> float:
    p = p or truck_params()
    r = float(revenue)
    return r - r * p["tax_pct"] - r * p["amortization_pct"] - float(costs)


def waterfall(
    *,
    rate_rub: float,
    fuel_rub: float,
    driver_rub: float,
    empty_risk_rub: float,
    p: dict[str, float] | None = None,
) -> dict[str, Any]:
    """Ставка → налог → амортизация → топливо → водитель → риск порожняка → чистыми."""
    p = p or truck_params()
    r = float(rate_rub)
    tax = r * p["tax_pct"]
    amort = r * p["amortization_pct"]
    fuel = float(fuel_rub)
    driver = float(driver_rub)
    risk = max(0.0, float(empty_risk_rub))
    net = r - tax - amort - fuel - driver - risk
    steps = [
        {"key": "rate", "label": "Ставка клиенту", "rub": round(r, 0), "sign": ""},
        {"key": "tax", "label": f"Налог {int(p['tax_pct'] * 100)}% от ставки", "rub": round(-tax, 0), "sign": "−"},
        {"key": "amort", "label": f"Амортизация {int(p['amortization_pct'] * 100)}%", "rub": round(-amort, 0), "sign": "−"},
        {"key": "fuel", "label": "Топливо", "rub": round(-fuel, 0), "sign": "−"},
        {"key": "driver", "label": "Водитель", "rub": round(-driver, 0), "sign": "−"},
        {"key": "empty_risk", "label": "Риск порожняка", "rub": round(-risk, 0), "sign": "−"},
        {"key": "net", "label": "Чистыми", "rub": round(net, 0), "sign": "="},
    ]
    return {"rate_rub": round(r, 0), "net_rub": round(net, 0), "steps": steps}


def price_outbound_leg(
    *,
    km: float,
    p_find_backhaul: float,
    p: dict[str, float] | None = None,
) -> dict[str, Any]:
    p = p or truck_params()
    km = float(km or 0)
    if km <= 0:
        return {"ok": False, "error": "Нет километража маршрута"}

    pf = max(0.0, min(1.0, float(p_find_backhaul)))
    fuel_one = fuel_rub_for_km(km, p)
    fuel_round = fuel_one * 2.0

    hours_empty = trip_hours(km_one_way=km, with_backhaul=False, p=p)
    hours_bh = trip_hours(km_one_way=km, with_backhaul=True, p=p)
    # Outbound-only leg (обратка оплачивает возврат): езда в одну сторону + одна ПРР
    speed = max(30.0, p["avg_speed_kmh"])
    hours_out = float(km) / speed + p["load_unload_hours"]
    days_empty = trip_days(hours_empty)
    days_bh = trip_days(hours_bh)
    days_out = trip_days(hours_out)
    driver_empty = days_empty * p["driver_day_rub"]
    driver_bh = days_bh * p["driver_day_rub"]
    driver_out = days_out * p["driver_day_rub"]

    # Порожняк: топливо туда-обратно + водитель на полный рейс.
    # С обраткой: топливо только «туда» (возврат закрывает обратка) + водитель на плечо «туда».
    costs_if_empty = fuel_round + driver_empty
    costs_if_bh = fuel_one + driver_out
    expected_costs = (1.0 - pf) * costs_if_empty + pf * costs_if_bh

    fuel_exp = (1.0 - pf) * fuel_round + pf * fuel_one
    driver_exp = (1.0 - pf) * driver_empty + pf * driver_out
    empty_risk = max(0.0, (1.0 - pf) * (costs_if_empty - costs_if_bh))

    r_min = revenue_for_target_net(costs=expected_costs, target_net=p["target_net_min"], p=p)
    r_mid = revenue_for_target_net(
        costs=expected_costs,
        target_net=(p["target_net_min"] + p["target_net_max"]) / 2.0,
        p=p,
    )
    r_max = revenue_for_target_net(costs=expected_costs, target_net=p["target_net_max"], p=p)
    r_empty_min = revenue_for_target_net(costs=costs_if_empty, target_net=p["target_net_min"], p=p)
    r_bh_min = revenue_for_target_net(costs=costs_if_bh, target_net=p["target_net_min"], p=p)
    r_bh_mid = revenue_for_target_net(
        costs=costs_if_bh,
        target_net=(p["target_net_min"] + p["target_net_max"]) / 2.0,
        p=p,
    )

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
        "fuel_expected_rub": round(fuel_exp, 0),
        "driver_empty_rub": round(driver_empty, 0),
        "driver_backhaul_rub": round(driver_bh, 0),
        "driver_outbound_rub": round(driver_out, 0),
        "driver_expected_rub": round(driver_exp, 0),
        "empty_risk_rub": round(empty_risk, 0),
        "costs_if_empty_rub": round(costs_if_empty, 0),
        "costs_if_backhaul_rub": round(costs_if_bh, 0),
        "expected_costs_rub": round(expected_costs, 0),
        "hours_outbound_leg": round(hours_out, 1),
        "days_outbound_leg": days_out,
        "suggested_min_total_rub": round(r_min, 0),
        "suggested_mid_total_rub": round(r_mid, 0),
        "suggested_max_total_rub": round(r_max, 0),
        "suggested_empty_safe_rub": round(r_empty_min, 0),
        "suggested_backhaul_min_rub": round(r_bh_min, 0),
        "suggested_backhaul_mid_rub": round(r_bh_mid, 0),
        "suggested_min_ppk": round(r_min / km, 1),
        "suggested_mid_ppk": round(r_mid / km, 1),
        "suggested_max_ppk": round(r_max / km, 1),
        "waterfall": waterfall(
            rate_rub=r_mid,
            fuel_rub=fuel_one,
            driver_rub=driver_out,
            empty_risk_rub=empty_risk,
            p=p,
        ),
        "scenarios": {
            "with_backhaul": {
                "label": "С обраткой",
                "costs_rub": round(costs_if_bh, 0),
                "suggest_min_rub": round(r_bh_min, 0),
                "suggest_mid_rub": round(r_bh_mid, 0),
                "ppk": round(r_bh_min / km, 1),
                "hours": round(hours_bh, 1),
                "days": days_bh,
            },
            "empty_return": {
                "label": "Без обратки",
                "costs_rub": round(costs_if_empty, 0),
                "suggest_min_rub": round(r_empty_min, 0),
                "suggest_mid_rub": round(
                    revenue_for_target_net(
                        costs=costs_if_empty,
                        target_net=(p["target_net_min"] + p["target_net_max"]) / 2.0,
                        p=p,
                    ),
                    0,
                ),
                "ppk": round(r_empty_min / km, 1),
                "hours": round(hours_empty, 1),
                "days": days_empty,
            },
        },
        "amortization_pct": p["amortization_pct"],
        "tax_pct": p["tax_pct"],
        "tax_on": "client_rate",
        "target_net_min": p["target_net_min"],
        "target_net_max": p["target_net_max"],
    }


def build_verdict(
    *,
    offer_rub: float | None,
    suggested_min: float | None,
    empty_safe: float | None,
    p_find: float,
    p: dict[str, float],
) -> dict[str, Any]:
    propose = float(suggested_min or 0)
    if propose <= 0:
        return {
            "action": "unknown",
            "label": "нет данных",
            "tone": "muted",
            "propose_rub": None,
            "text": "Недостаточно данных для ставки",
        }
    if offer_rub is None:
        return {
            "action": "propose",
            "label": "предлагать от",
            "tone": "propose",
            "propose_rub": round(propose, 0),
            "text": f"Предлагайте от {int(propose):,} ₽".replace(",", " "),
        }
    offer = float(offer_rub)
    if offer >= propose:
        return {
            "action": "take",
            "label": "брать",
            "tone": "take",
            "propose_rub": round(propose, 0),
            "text": f"Можно брать · порог {int(propose):,} ₽".replace(",", " "),
        }
    if empty_safe and offer < float(empty_safe) * 0.85 and p_find < 0.25:
        return {
            "action": "skip",
            "label": "мимо",
            "tone": "skip",
            "propose_rub": round(propose, 0),
            "text": f"Слабая обратка и ставка низкая · нужно от {int(propose):,} ₽".replace(",", " "),
        }
    return {
        "action": "raise",
        "label": "поднять",
        "tone": "raise",
        "propose_rub": round(propose, 0),
        "text": f"Поднять до {int(propose):,} ₽ (+{int(propose - offer):,} ₽)".replace(",", " "),
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
        "waterfall": waterfall(
            rate_rub=float(offer_rub),
            fuel_rub=float(priced["fuel_one_way_rub"]),
            driver_rub=float(priced["driver_outbound_rub"]),
            empty_risk_rub=float(priced["empty_risk_rub"]),
            p=p,
        ),
    }
