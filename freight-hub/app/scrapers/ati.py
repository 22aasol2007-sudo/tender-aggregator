"""ATI.SU — official API only when ATI_API_TOKEN is set."""

from __future__ import annotations

import logging
from typing import Any

import httpx

from app import config
from app.models import RawLoad

log = logging.getLogger("scraper.ati")

# Documented ATI.SU public API host (loads search). Requires personal token.
ATI_BASE = "https://api.ati.su"


class AtiScraper:
    name = "ati"

    def __init__(self, token: str | None = None) -> None:
        self.token = (token or "").strip()

    async def fetch(self) -> list[RawLoad]:
        if not self.token:
            log.info("ati skipped — set ATI_API_TOKEN for legal API access")
            return []
        headers = {
            "Authorization": f"Bearer {self.token}",
            "Accept": "application/json",
            "User-Agent": config.USER_AGENT,
        }
        out: list[RawLoad] = []
        # Minimal search around Moscow corridor; endpoint may vary by ATI account plan.
        payloads = [
            {"from": {"city": "Москва"}, "limit": 50},
            {"to": {"city": "Москва"}, "limit": 50},
        ]
        async with httpx.AsyncClient(timeout=40.0, headers=headers, follow_redirects=True) as client:
            for path in ("/v1.0/loads/search", "/v2/loads/search", "/gw/loads/search"):
                for body in payloads:
                    try:
                        r = await client.post(f"{ATI_BASE}{path}", json=body)
                        if r.status_code in (401, 403):
                            log.warning("ati auth rejected (%s) — check ATI_API_TOKEN", r.status_code)
                            return []
                        if r.status_code == 404:
                            break
                        if r.status_code != 200:
                            log.debug("ati %s -> %s", path, r.status_code)
                            continue
                        data = r.json()
                        out.extend(self._parse(data))
                        if out:
                            log.info("ati fetched %s via %s", len(out), path)
                            return out
                    except Exception as exc:
                        log.debug("ati %s: %s", path, exc)
        if not out:
            log.warning("ati token set but no loads returned — verify API path for your account")
        return out

    def _parse(self, data: Any) -> list[RawLoad]:
        rows: list[Any]
        if isinstance(data, list):
            rows = data
        elif isinstance(data, dict):
            rows = data.get("loads") or data.get("items") or data.get("data") or []
        else:
            rows = []
        out: list[RawLoad] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            eid = str(row.get("id") or row.get("load_id") or row.get("number") or "")
            if not eid:
                continue
            frm = self._city(row.get("loading") or row.get("from") or row.get("loading_city"))
            to = self._city(row.get("unloading") or row.get("to") or row.get("unloading_city"))
            price = row.get("price") or row.get("rate")
            if isinstance(price, (int, float)):
                price = f"{int(price)} руб"
            tonnage = row.get("weight") or row.get("tonnage")
            try:
                tonnage_f = float(tonnage) if tonnage is not None else None
            except (TypeError, ValueError):
                tonnage_f = None
            url = row.get("url") or row.get("link") or f"https://ati.su/loads/{eid}"
            body = (
                f"Есть груз. {frm or '?'} → {to or '?'}. "
                f"{row.get('cargo') or row.get('note') or ''} Ищу машину."
            )[:2000]
            out.append(
                RawLoad(
                    source=self.name,
                    external_id=eid,
                    title=f"{frm or '?'} → {to or '?'} #{eid}",
                    body=body,
                    from_city=frm,
                    to_city=to,
                    tonnage=tonnage_f,
                    price=str(price) if price else None,
                    url=str(url),
                    raw=row,
                )
            )
        return out

    @staticmethod
    def _city(val: Any) -> str | None:
        if isinstance(val, str) and val.strip():
            return val.strip()
        if isinstance(val, dict):
            for k in ("city", "name", "city_name"):
                if val.get(k):
                    return str(val[k]).strip()
        return None
