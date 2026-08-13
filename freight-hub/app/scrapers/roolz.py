"""Roolz public exchange — SSR preload + offer detail API."""

from __future__ import annotations

import json
import logging
import re
from typing import Any

import httpx

from app import config
from app.models import RawLoad
from app.scrapers.board_common import exact_city, infer_body

log = logging.getLogger("scraper.roolz")

FIND_URL = "https://roolz.net/ru/find-cargo"
OFFER_API = "https://api.srv.roolz.net/exchange/v1/public/offers/{oid}"


class RoolzScraper:
    name = "roolz"

    async def fetch(self) -> list[RawLoad]:
        headers = {
            "User-Agent": config.USER_AGENT,
            "Accept-Language": "ru-RU,ru;q=0.9",
            "Accept": "text/html,application/xhtml+xml",
        }
        out: list[RawLoad] = []
        async with httpx.AsyncClient(timeout=40.0, headers=headers, follow_redirects=True) as client:
            try:
                r = await client.get(FIND_URL)
                r.raise_for_status()
            except Exception as exc:
                log.warning("roolz find-cargo: %s", exc)
                return []
            offers = self._preload_offers(r.text)
            api_headers = {
                "User-Agent": config.USER_AGENT,
                "Accept": "application/json",
                "Origin": "https://roolz.net",
                "Referer": FIND_URL,
            }
            for raw in offers:
                oid = str(raw.get("_id") or "")
                if not oid:
                    continue
                detail = raw
                try:
                    dr = await client.get(OFFER_API.format(oid=oid), headers=api_headers)
                    if dr.status_code == 200 and "json" in dr.headers.get("content-type", ""):
                        payload = dr.json()
                        if isinstance(payload, dict) and isinstance(payload.get("result"), dict):
                            detail = payload["result"]
                except Exception:
                    pass
                item = self._map(detail)
                if item:
                    out.append(item)
        log.info("roolz fetched %s", len(out))
        return out

    def _preload_offers(self, html: str) -> list[dict[str, Any]]:
        m = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', html, re.S)
        if not m:
            return []
        try:
            nd = json.loads(m.group(1))
            preload = ((nd.get("props") or {}).get("pageProps") or {}).get("preload")
            if isinstance(preload, str):
                preload = json.loads(preload)
            if isinstance(preload, list) and preload:
                block = preload[0]
            elif isinstance(preload, dict):
                block = preload
            else:
                return []
            result = block.get("result") or []
            return [x for x in result if isinstance(x, dict)]
        except Exception as exc:
            log.warning("roolz parse NEXT_DATA: %s", exc)
            return []

    def _map(self, row: dict[str, Any]) -> RawLoad | None:
        oid = str(row.get("_id") or "")
        if not oid:
            return None
        route = row.get("route") or []
        cities: list[str] = []
        for pt in route:
            if not isinstance(pt, dict):
                continue
            addr = ((pt.get("location") or {}).get("address") or {})
            city = addr.get("city") or ""
            if city:
                city = re.sub(r"^(город|г\.)\s+", "", str(city), flags=re.I).strip()
                c = exact_city(city)
                if c:
                    cities.append(c)
                    continue
            # fallback state/region name only if no city
            state = addr.get("state_name") or ""
            if state and not cities:
                c = exact_city(str(state).replace(" область", "").replace("Область", "").strip())
                if c:
                    cities.append(c)
        frm = cities[0] if cities else None
        to = cities[-1] if len(cities) >= 2 else None
        # cargo params
        cargo = row.get("cargo") or row.get("transport") or {}
        if not isinstance(cargo, dict):
            cargo = {}
        tonnage = None
        for key in ("weight", "weight_ton", "tonnage", "max_weight"):
            if cargo.get(key) not in (None, ""):
                try:
                    tonnage = float(cargo[key])
                    break
                except (TypeError, ValueError):
                    pass
        volume = None
        for key in ("volume", "volume_m3", "max_volume"):
            if cargo.get(key) not in (None, ""):
                try:
                    volume = float(cargo[key])
                    break
                except (TypeError, ValueError):
                    pass
        name = row.get("offer_name") or oid
        desc = row.get("description") or ""
        blob = f"{name} {desc} {cargo}"
        # parse "20t, 86m3" from offer_name
        if tonnage is None:
            tm = re.search(r"(\d+[.,]?\d*)\s*t\b", name, re.I)
            if tm:
                tonnage = float(tm.group(1).replace(",", "."))
        if volume is None:
            vm = re.search(r"(\d+[.,]?\d*)\s*m3\b", name, re.I)
            if vm:
                volume = float(vm.group(1).replace(",", "."))
        body = f"Есть груз. {frm or '?'} → {to or '?'}. {name}. {desc}. Ищу машину."[:2000]
        return RawLoad(
            source=self.name,
            external_id=oid,
            title=f"{frm or '?'} → {to or '?'} #{oid}",
            body=body,
            from_city=frm,
            to_city=to,
            tonnage=tonnage,
            volume_m3=volume,
            body_type=infer_body(blob),
            url=f"https://roolz.net/ru/offer/{oid}",
            raw=row,
        )
