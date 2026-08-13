from __future__ import annotations

import logging
from typing import Any

import httpx

from app import config
from app.models import RawLoad
from app.parse import _canon_city

log = logging.getLogger("scraper.papacargo")


class PapaCargoScraper:
    name = "papacargo"

    def __init__(self, pages: int = 3) -> None:
        self.pages = pages

    async def fetch(self) -> list[RawLoad]:
        out: list[RawLoad] = []
        headers = {
            "User-Agent": config.USER_AGENT,
            "Accept": "application/json",
            "X-Requested-With": "XMLHttpRequest",
            "Referer": "https://papacargo.com/loads",
            "Accept-Language": "ru",
        }
        async with httpx.AsyncClient(timeout=30.0, headers=headers, follow_redirects=True) as client:
            for page in range(1, self.pages + 1):
                r = await client.get(
                    "https://papacargo.com/api/loads/search",
                    params={"page": page},
                )
                r.raise_for_status()
                data = r.json()
                rows = data.get("data") or []
                if not rows:
                    break
                for row in rows:
                    item = self._map(row)
                    if item:
                        out.append(item)
        log.info("papacargo fetched %s", len(out))
        return out

    def _map(self, row: dict[str, Any]) -> RawLoad | None:
        lid = row.get("id")
        if lid is None:
            return None
        frm = (row.get("from") or {}).get("name") or ""
        to = (row.get("to") or {}).get("name") or ""
        weight = row.get("total_weight")
        volume = row.get("total_volume")
        name = row.get("cargo_name") or "Груз"
        try:
            tonnage = float(str(weight).replace(",", ".")) if weight not in (None, "") else None
        except ValueError:
            tonnage = None
        try:
            volume_m3 = float(str(volume).replace(",", ".").replace(" ", "")) if volume not in (None, "") else None
        except ValueError:
            volume_m3 = None

        # Infer body from cargo name / transport hints in row
        body_type = None
        blob = f"{name} {row}".lower()
        if "реф" in blob or "refriger" in blob:
            body_type = "reefer"
        elif "изотерм" in blob:
            body_type = "isotherm"
        elif "тент" in blob or "curtain" in blob:
            body_type = "tent"

        from_city = _canon_city(frm.split(",")[0]) or frm.split(",")[0].strip().lower() or None
        to_city = _canon_city(to.split(",")[0]) or to.split(",")[0].strip().lower() or None

        body = (
            f"Есть груз: {name}. {frm} → {to}. "
            f"{tonnage or '?'} т / {volume_m3 or '?'} м³. "
            f"Дата: {row.get('date') or '—'}. Ищу машину."
        )
        price = None
        from app.scrapers.board_common import parse_iso_datetime, parse_posted_at_ru

        posted_at = None
        for key in ("created_at", "updated_at", "published_at", "date", "datetime"):
            val = row.get(key)
            if val in (None, ""):
                continue
            if isinstance(val, (int, float)):
                posted_at = parse_iso_datetime(str(int(val)))
            else:
                posted_at = parse_iso_datetime(str(val)) or parse_posted_at_ru(str(val))
            if posted_at:
                break
        # payment fields vary
        return RawLoad(
            source=self.name,
            external_id=str(lid),
            title=f"{frm} → {to}",
            body=body,
            from_city=from_city,
            to_city=to_city,
            tonnage=tonnage,
            volume_m3=volume_m3,
            body_type=body_type,
            price=price,
            url=f"https://papacargo.com/loads/{lid}",
            posted_at=posted_at,
            raw=row,
        )
