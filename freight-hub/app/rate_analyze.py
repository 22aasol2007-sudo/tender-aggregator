"""Route profitability / backhaul liquidity analysis for one truck."""

from __future__ import annotations

import asyncio
import logging
import re
import statistics
import time
from typing import Any
from urllib.parse import quote

import httpx
from bs4 import BeautifulSoup

from app import config
from app.ingest import calc_price_per_km
from app.truck_economics import evaluate_offer, price_outbound_leg, truck_params

log = logging.getLogger("rate_analyze")

DEFAULT_LOADED_PPK = 85.0


def _median(vals: list[float]) -> float | None:
    clean = [float(v) for v in vals if v is not None]
    if not clean:
        return None
    return float(statistics.median(clean))


def _risk_label(p_backhaul: float, backhaul_n: int) -> str:
    if backhaul_n >= 12 and p_backhaul >= 0.55:
        return "низкий"
    if backhaul_n >= 4 and p_backhaul >= 0.35:
        return "средний"
    return "высокий"


def _p_find(backhaul_n: int, peer_median: float | None) -> float:
    """Probability-ish of finding a backhaul before leaving empty."""
    base = backhaul_n / (backhaul_n + 4.0)
    if peer_median and peer_median > 0:
        rel = min(1.6, backhaul_n / peer_median)
        base *= 0.65 + 0.35 * min(1.0, rel)
    return max(0.05, min(0.92, base))


def _norm(s: str) -> str:
    return (s or "").strip().lower().replace("ё", "е")


class RateAnalyzer:
    def __init__(self, db: Any) -> None:
        self.db = db

    async def analyze(
        self,
        *,
        base: str,
        destination: str,
        offer_rub: float | None = None,
        tonnage: float | None = None,
        body: str | None = None,
        live_probe: bool = True,
        route_km_override: float | None = None,
        from_city: str | None = None,
    ) -> dict[str, Any]:
        base_n = _norm(base or "москва") or "москва"
        dest_n = _norm(destination or "")
        if not dest_n:
            return {"ok": False, "error": "Укажите город выгрузки"}

        params = truck_params()
        radius = float(params["backhaul_radius_km"])
        load_from = _norm(from_city) if from_city else None

        route_km = None
        # Prefer actual loading city from the ad when present
        if load_from:
            route_km, _ = calc_price_per_km(None, load_from, dest_n)
        if route_km is None:
            route_km, _ = calc_price_per_km(None, base_n, dest_n)
        if route_km is None:
            route_km, _ = calc_price_per_km(None, dest_n, base_n)
        if route_km is None and route_km_override:
            try:
                route_km = float(route_km_override)
            except (TypeError, ValueError):
                route_km = None
        elif route_km_override:
            # Trust ATI km if close or if geo missing precision for villages
            try:
                listed = float(route_km_override)
                if route_km is None or abs(listed - float(route_km)) / max(listed, 1) > 0.25:
                    # if listed differs a lot, still prefer listed from ATI card
                    if listed > 20:
                        route_km = listed
            except (TypeError, ValueError):
                pass

        outbound = await self.db.route_stats(from_city=base_n, to_city=dest_n, days=7)
        backhaul = await self.db.route_stats(from_city=dest_n, to_city=base_n, days=7)
        backhaul_broad = await self.db.backhaul_to_base_stats(origin=dest_n, base=base_n, days=7)
        nearby = await self.db.backhaul_nearby_to_base(
            origin=dest_n, base=base_n, radius_km=radius, days=7, limit=15
        )
        ranking = await self.db.backhaul_city_ranking(base=base_n, days=7, limit=25)

        peer_counts = [int(r["backhaul_n"]) for r in ranking if r.get("city") != dest_n]
        peer_median = _median([float(x) for x in peer_counts]) if peer_counts else None

        dest_rank = None
        dest_rank_row = None
        for i, row in enumerate(ranking, start=1):
            city = _norm(str(row.get("city") or ""))
            if city == dest_n or dest_n in city or city in dest_n:
                dest_rank = i
                dest_rank_row = row
                break

        feed_exact = max(
            int(backhaul_broad.get("count") or 0),
            int(backhaul.get("count") or 0),
            int(dest_rank_row.get("backhaul_n") or 0) if dest_rank_row else 0,
        )
        feed_radius = int(nearby.get("count") or 0)
        feed_n = max(feed_exact, feed_radius)

        live: dict[str, Any] = {"ok": False, "sources": [], "unwired_total": 0, "wired_live_total": 0}
        external_n = 0
        if live_probe:
            try:
                live = await probe_external_backhaul(dest_n, base_n)
                external_n = int(live.get("unwired_total") or 0)
            except Exception as exc:
                log.warning("live probe failed: %s", exc)
                live = {"ok": False, "error": str(exc), "sources": [], "unwired_total": 0, "wired_live_total": 0}

        backhaul_n = feed_n + external_n
        p_find = _p_find(backhaul_n, peer_median)
        risk = _risk_label(p_find, backhaul_n)

        out_ppk = outbound.get("median_ppk") or DEFAULT_LOADED_PPK
        bh_ppk = backhaul_broad.get("median_ppk") or backhaul.get("median_ppk")
        km = float(route_km or 0)

        econ = price_outbound_leg(km=km, p_find_backhaul=p_find, p=params) if km > 0 else {"ok": False, "error": "нет км"}
        suggested_min_total = econ.get("suggested_min_total_rub") if econ.get("ok") else None
        suggested_mid_total = econ.get("suggested_mid_total_rub") if econ.get("ok") else None
        suggested_max_total = econ.get("suggested_max_total_rub") if econ.get("ok") else None
        suggested_min_ppk = econ.get("suggested_min_ppk") if econ.get("ok") else None

        offer_eval = None
        if offer_rub is not None and km > 0 and econ.get("ok"):
            offer_eval = evaluate_offer(
                offer_rub=float(offer_rub),
                km=km,
                p_find_backhaul=p_find,
                p=params,
            )

        sources_used = await self.db.stats_sources_in_window(days=7)
        route_label_from = load_from or base_n

        return {
            "ok": True,
            "base": base_n,
            "destination": dest_n,
            "from_city": route_label_from,
            "route_km": round(km, 1) if km else None,
            "tonnage": tonnage,
            "body": body,
            "truck": {
                "load_unload_hours": params["load_unload_hours"],
                "driver_day_rub": params["driver_day_rub"],
                "fuel_l_per_100km": params["fuel_l_per_100km"],
                "diesel_rub_per_l": params["diesel_rub_per_l"],
                "amortization_pct": params["amortization_pct"],
                "tax_pct": params["tax_pct"],
                "target_net_min": params["target_net_min"],
                "target_net_max": params["target_net_max"],
                "avg_speed_kmh": params["avg_speed_kmh"],
                "backhaul_radius_km": radius,
            },
            "outbound": {
                "count": int(outbound.get("count") or 0),
                "median_ppk": outbound.get("median_ppk"),
                "median_price": outbound.get("median_price"),
            },
            "backhaul": {
                "count": backhaul_n,
                "count_feed": feed_n,
                "count_exact": feed_exact,
                "count_radius": int(nearby.get("count_radius") or 0),
                "count_external": external_n,
                "radius_km": radius,
                "median_ppk": bh_ppk,
                "median_price": backhaul_broad.get("median_price") or backhaul.get("median_price"),
                "p_find": round(p_find, 2),
                "risk": risk,
                "rank": dest_rank,
                "peers": len(ranking),
                "peer_median_backhaul": round(peer_median, 1) if peer_median is not None else None,
                "nearby_cities": nearby.get("cities") or [],
            },
            "economics": econ if econ.get("ok") else None,
            "pricing": {
                "market_outbound_ppk": round(float(out_ppk), 1),
                "expected_costs_rub": econ.get("expected_costs_rub") if econ.get("ok") else None,
                "costs_if_empty_rub": econ.get("costs_if_empty_rub") if econ.get("ok") else None,
                "fuel_round_rub": econ.get("fuel_round_rub") if econ.get("ok") else None,
                "driver_empty_rub": econ.get("driver_empty_rub") if econ.get("ok") else None,
                "hours_empty_return": econ.get("hours_empty_return") if econ.get("ok") else None,
                "days_empty_return": econ.get("days_empty_return") if econ.get("ok") else None,
                "suggested_min_total_rub": suggested_min_total,
                "suggested_mid_total_rub": suggested_mid_total,
                "suggested_max_total_rub": suggested_max_total,
                "suggested_empty_safe_rub": econ.get("suggested_empty_safe_rub") if econ.get("ok") else None,
                "suggested_min_ppk": suggested_min_ppk,
                "suggested_mid_ppk": econ.get("suggested_mid_ppk") if econ.get("ok") else None,
                "target_net_min": params["target_net_min"],
                "target_net_max": params["target_net_max"],
                "offer": offer_eval,
            },
            "ranking": ranking[:15],
            "live_external": live,
            "feed_sources": sources_used,
            "notes": [
                f"Машина: дизель {int(params['fuel_l_per_100km'])} л/100 км × {int(params['diesel_rub_per_l'])} ₽, водитель {int(params['driver_day_rub'])} ₽/сут.",
                f"Погрузка+выгрузка ≈ {params['load_unload_hours']} ч, амортизация {int(params['amortization_pct']*100)}%, налог {int(params['tax_pct']*100)}%.",
                f"Целевая чистая прибыль {int(params['target_net_min'])}–{int(params['target_net_max'])} ₽ на рейс.",
                f"Обратка: город выгрузки + радиус {int(radius)} км к «{base_n}» (лента 7 суток + live внешних площадок).",
                "Порожний возврат в расчёте заложен с вероятностью (1 − p_find).",
            ] + (
                []
                if km > 0
                else ["Не удалось определить километраж — ставка не посчитана. Проверьте города или км на скрине."]
            ),
            "updated_at": time.time(),
        }


async def probe_external_backhaul(origin: str, base: str) -> dict[str, Any]:
    """Probe boards — unwired platforms count toward risk; wired shown for transparency."""
    headers = {
        "User-Agent": config.USER_AGENT,
        "Accept-Language": "ru-RU,ru;q=0.9",
        "Accept": "text/html,application/xhtml+xml,application/json",
    }
    tasks = [
        _probe_ati_public(origin, base, headers),
        _probe_ati_if_token(origin, base, headers),
        _probe_svezem(origin, base, headers),
        _probe_cargomart(origin, base, headers),
        _probe_monopoly_status(headers),
        # Wired boards — live snapshot only (not added to unwired_total)
        _probe_papacargo(origin, base, headers),
        _probe_vezetvsem(origin, base, headers),
        _probe_perevozka24(origin, base, headers),
        _probe_avtodispetcher(origin, base, headers),
    ]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    sources: list[dict[str, Any]] = []
    unwired_total = 0
    wired_live_total = 0
    for res in results:
        if isinstance(res, Exception):
            sources.append({"ok": False, "error": str(res)})
            continue
        if not res:
            continue
        sources.append(res)
        if not res.get("ok"):
            continue
        n = int(res.get("count") or 0)
        if res.get("wired"):
            wired_live_total += n
        else:
            unwired_total += n
    return {
        "ok": True,
        "total": unwired_total,
        "unwired_total": unwired_total,
        "wired_live_total": wired_live_total,
        "sources": sources,
    }


async def _probe_ati_if_token(origin: str, base: str, headers: dict[str, str]) -> dict[str, Any]:
    token = (getattr(config, "ATI_API_TOKEN", "") or "").strip()
    if not token:
        return {
            "name": "ati_api",
            "ok": False,
            "wired": False,
            "count": 0,
            "note": "нет ATI_API_TOKEN — API недоступен",
        }
    h = {**headers, "Authorization": f"Bearer {token}", "Accept": "application/json"}
    async with httpx.AsyncClient(timeout=30.0, headers=h, follow_redirects=True) as client:
        for path in ("/v1.0/loads/search", "/v2/loads/search", "/gw/loads/search"):
            try:
                r = await client.post(
                    f"https://api.ati.su{path}",
                    json={
                        "from": {"city": origin.title()},
                        "to": {"city": base.title()},
                        "limit": 50,
                    },
                )
                if r.status_code in (401, 403):
                    return {"name": "ati_api", "ok": False, "wired": False, "count": 0, "note": f"auth {r.status_code}"}
                if r.status_code != 200:
                    continue
                data = r.json()
                rows = data if isinstance(data, list) else (data.get("loads") or data.get("items") or [])
                count = len(rows) if isinstance(rows, list) else 0
                return {"name": "ati_api", "ok": True, "wired": False, "count": count}
            except Exception as exc:
                return {"name": "ati_api", "ok": False, "wired": False, "count": 0, "error": str(exc)}
    return {
        "name": "ati_api",
        "ok": False,
        "wired": False,
        "count": 0,
        "note": "токен есть, но метод поиска пуст (нужны boardIds/лицензия)",
    }


async def _probe_ati_public(origin: str, base: str, headers: dict[str, str]) -> dict[str, Any]:
    """Best-effort public ATI loads board HTML (no login) — count only."""
    o, b = _norm(origin), _norm(base)
    urls = [
        "https://loads.ati.su/",
        "https://loads.ati.su/russia",
        f"https://loads.ati.su/?filter=true&from={quote(origin)}&to={quote(base)}",
    ]
    count = 0
    note = "публичная витрина"
    async with httpx.AsyncClient(timeout=25.0, headers=headers, follow_redirects=True) as client:
        for url in urls:
            try:
                r = await client.get(url)
                if r.status_code != 200:
                    continue
                text = r.text
                low = text.lower().replace("ё", "е")
                # SPA shell often has no cards — detect that
                if "window.__INITIAL" in text or "ati-loads" in low or "load-item" in low:
                    soup = BeautifulSoup(text, "lxml")
                    cards = soup.select(
                        "[class*='load'], [class*='Load'], .loads-list tr, .load-card, article"
                    )
                    for el in cards[:80]:
                        blob = _norm(el.get_text(" ", strip=True))
                        if o in blob and b in blob and blob.find(o) < blob.find(b):
                            count += 1
                    if count:
                        break
                # Fallback: count JSON-ish city pairs in preload
                for m in re.finditer(r'"cityName"\s*:\s*"([^"]+)"', text):
                    pass
                if count == 0 and ("логин" in low or "войти" in low) and "груз" not in low[:2000]:
                    note = "витрина требует логин / SPA без SSR"
                    break
            except Exception as exc:
                return {"name": "ati_public", "ok": False, "wired": False, "count": 0, "error": str(exc)}
    if count == 0:
        return {
            "name": "ati_public",
            "ok": False,
            "wired": False,
            "count": 0,
            "note": note + " — без токена полный рынок ATI недоступен",
        }
    return {"name": "ati_public", "ok": True, "wired": False, "count": count, "note": note}


async def _probe_svezem(origin: str, base: str, headers: dict[str, str]) -> dict[str, Any]:
    o, b = _norm(origin), _norm(base)
    urls = [
        f"https://svezem.ru/cargo/search/?from={quote(origin)}&to={quote(base)}",
        f"https://svezem.ru/cargo/search/from-{_slug(origin)}-to-{_slug(base)}/",
        "https://svezem.ru/cargo/search/",
    ]
    count = 0
    async with httpx.AsyncClient(timeout=25.0, headers=headers, follow_redirects=True) as client:
        for url in urls:
            try:
                r = await client.get(url)
                if r.status_code != 200:
                    continue
                soup = BeautifulSoup(r.text, "lxml")
                cards = (
                    soup.select(".cargo-item, .cargo_item, .search-item, [class*='cargo']")
                    or soup.select("article, .card, li")
                )
                for el in cards[:100]:
                    blob = _norm(el.get_text(" ", strip=True))
                    if len(blob) < 20:
                        continue
                    if o in blob and b in blob and blob.find(o) <= blob.find(b):
                        count += 1
                if count:
                    break
                # Text fallback on listing page
                low = _norm(r.text)
                if o in low and b in low:
                    # weak signal: mention density
                    hits = len(re.findall(re.escape(o), low))
                    if hits >= 2:
                        count = max(count, min(hits, 15))
                        break
            except Exception as exc:
                return {"name": "svezem", "ok": False, "wired": False, "count": 0, "error": str(exc)}
    return {"name": "svezem", "ok": True, "wired": False, "count": count}


async def _probe_cargomart(origin: str, base: str, headers: dict[str, str]) -> dict[str, Any]:
    o, b = _norm(origin), _norm(base)
    urls = [
        "https://cargomart.ru/orders",
        "https://cargomart.ru/carrier/orders",
        f"https://cargomart.ru/orders?from={quote(origin)}&to={quote(base)}",
    ]
    count = 0
    note = ""
    async with httpx.AsyncClient(timeout=25.0, headers=headers, follow_redirects=True) as client:
        for url in urls:
            try:
                r = await client.get(url)
                if r.status_code in (401, 403):
                    return {
                        "name": "cargomart",
                        "ok": False,
                        "wired": False,
                        "count": 0,
                        "note": "нужна авторизация перевозчика",
                    }
                if r.status_code != 200:
                    continue
                low = _norm(r.text)
                if "войти" in low and "заказ" not in low[:3000]:
                    note = "лента за логином"
                    continue
                soup = BeautifulSoup(r.text, "lxml")
                cards = soup.select("[class*='order'], [class*='Order'], .trip, article")
                for el in cards[:80]:
                    blob = _norm(el.get_text(" ", strip=True))
                    if o in blob and b in blob and blob.find(o) <= blob.find(b):
                        count += 1
                if count:
                    break
            except Exception as exc:
                return {"name": "cargomart", "ok": False, "wired": False, "count": 0, "error": str(exc)}
    if count == 0:
        return {
            "name": "cargomart",
            "ok": False,
            "wired": False,
            "count": 0,
            "note": note or "публичных карточек нет / нужен кабинет",
        }
    return {"name": "cargomart", "ok": True, "wired": False, "count": count}


async def _probe_monopoly_status(headers: dict[str, str]) -> dict[str, Any]:
    token = (getattr(config, "MONOPOLY_API_TOKEN", "") or "").strip()
    if not token:
        return {
            "name": "monopoly",
            "ok": False,
            "wired": False,
            "count": 0,
            "note": "нет MONOPOLY_API_TOKEN — публичной ленты нет",
        }
    return {
        "name": "monopoly",
        "ok": False,
        "wired": False,
        "count": 0,
        "note": "токен задан, но официальный cargo-client ещё не подключён",
    }


async def _probe_papacargo(origin: str, base: str, headers: dict[str, str]) -> dict[str, Any]:
    o, b = _norm(origin), _norm(base)
    count = 0
    h = {
        **headers,
        "Accept": "application/json",
        "X-Requested-With": "XMLHttpRequest",
        "Referer": "https://papacargo.com/loads",
    }
    async with httpx.AsyncClient(timeout=25.0, headers=h, follow_redirects=True) as client:
        try:
            for page in (1, 2, 3):
                r = await client.get("https://papacargo.com/api/loads/search", params={"page": page})
                if r.status_code != 200:
                    break
                rows = (r.json() or {}).get("data") or []
                if not rows:
                    break
                for row in rows:
                    if not isinstance(row, dict):
                        continue
                    frm = _norm(str((row.get("from") or {}).get("name") or ""))
                    to = _norm(str((row.get("to") or {}).get("name") or ""))
                    if o in frm and b in to:
                        count += 1
        except Exception as exc:
            return {"name": "papacargo", "ok": False, "wired": True, "count": 0, "error": str(exc)}
    return {"name": "papacargo", "ok": True, "wired": True, "count": count}


async def _probe_vezetvsem(origin: str, base: str, headers: dict[str, str]) -> dict[str, Any]:
    o, b = _norm(origin), _norm(base)
    urls = [
        f"https://www.vezetvsem.ru/listing/{_slug(o)}",
        "https://www.vezetvsem.ru/listing/all",
    ]
    count = 0
    async with httpx.AsyncClient(timeout=25.0, headers=headers, follow_redirects=True) as client:
        for url in urls:
            try:
                r = await client.get(url)
                if r.status_code != 200:
                    continue
                soup = BeautifulSoup(r.text, "lxml")
                for el in soup.select(".x-order-main-part"):
                    frm_el = el.select_one(".from-town-name")
                    to_el = el.select_one(".to-town-name")
                    frm = _norm(frm_el.get_text(strip=True) if frm_el else "")
                    to = _norm(to_el.get_text(strip=True) if to_el else "")
                    if o in frm and b in to:
                        count += 1
                if count:
                    break
            except Exception:
                continue
    return {"name": "vezetvsem", "ok": True, "wired": True, "count": count}


async def _probe_perevozka24(origin: str, base: str, headers: dict[str, str]) -> dict[str, Any]:
    o, b = _norm(origin), _norm(base)
    count = 0
    async with httpx.AsyncClient(timeout=25.0, headers=headers, follow_redirects=True) as client:
        try:
            r = await client.get("https://perevozka24.ru/poisk-gruzov")
            if r.status_code != 200:
                return {"name": "perevozka24", "ok": False, "wired": True, "count": 0, "note": f"HTTP {r.status_code}"}
            soup = BeautifulSoup(r.text, "lxml")
            cards = soup.select(".offer-item-wrapper") or soup.select(".offer_main")
            for el in cards:
                text = _norm(el.get_text(" ", strip=True))
                if o in text and b in text and text.find(o) < text.find(b):
                    count += 1
        except Exception as exc:
            return {"name": "perevozka24", "ok": False, "wired": True, "count": 0, "error": str(exc)}
    return {"name": "perevozka24", "ok": True, "wired": True, "count": count}


async def _probe_avtodispetcher(origin: str, base: str, headers: dict[str, str]) -> dict[str, Any]:
    o, b = _norm(origin), _norm(base)
    count = 0
    url = f"https://www.avtodispetcher.ru/consignor/?f={quote(origin.title())}"
    async with httpx.AsyncClient(timeout=25.0, headers=headers, follow_redirects=True) as client:
        try:
            r = await client.get(url)
            if r.status_code != 200:
                return {"name": "avtodispetcher", "ok": False, "wired": True, "count": 0, "note": f"HTTP {r.status_code}"}
            soup = BeautifulSoup(r.text, "lxml")
            for tr in soup.select("table tr"):
                text = _norm(tr.get_text(" ", strip=True))
                if o in text and b in text and text.find(o) < text.find(b):
                    count += 1
        except Exception as exc:
            return {"name": "avtodispetcher", "ok": False, "wired": True, "count": 0, "error": str(exc)}
    return {"name": "avtodispetcher", "ok": True, "wired": True, "count": count}


def _slug(city: str) -> str:
    table = {
        "москва": "moskva",
        "санкт-петербург": "sankt-peterburg",
        "петербург": "sankt-peterburg",
        "казань": "kazan",
        "самара": "samara",
        "нижний новгород": "nizhniy-novgorod",
        "воронеж": "voronezh",
        "тула": "tula",
        "ярославль": "yaroslavl",
        "уфа": "ufa",
        "пермь": "perm",
        "тверь": "tver",
        "рязань": "ryazan",
        "калуга": "kaluga",
    }
    key = _norm(city)
    return table.get(key, re.sub(r"[^a-z0-9а-я]+", "-", key).strip("-") or "all")
