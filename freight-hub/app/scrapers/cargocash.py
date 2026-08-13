"""CargoCash public orders board."""

from __future__ import annotations

import logging
import re

import httpx
from bs4 import BeautifulSoup

from app import config
from app.models import RawLoad
from app.scrapers.board_common import CFD_NWFD_PFO_REGIONS, exact_city, infer_body, parse_tonnage

log = logging.getLogger("scraper.cargocash")

_BODY_PATHS = [
    "20tonn",
    "10tonn",
    "gazel",
    "tentovannyj_kuzov",
    "refrizherator",
    "izotermicheskij_kuzov",
    "furgon",
    "bortovoj_kuzov",
]


class CargoCashScraper:
    name = "cargocash"

    def __init__(self, list_pages: int = 25) -> None:
        self.list_pages = list_pages

    async def fetch(self) -> list[RawLoad]:
        headers = {
            "User-Agent": config.USER_AGENT,
            "Accept-Language": "ru-RU,ru;q=0.9",
            "X-Requested-With": "XMLHttpRequest",
            "Referer": "https://cargocash.ru/orders",
        }
        by_id: dict[str, RawLoad] = {}
        async with httpx.AsyncClient(timeout=40.0, headers=headers, follow_redirects=True) as client:
            for page in range(1, self.list_pages + 1):
                try:
                    r = await client.get(
                        "https://cargocash.ru/back/orders/list",
                        params={"page": page},
                    )
                    if r.status_code != 200:
                        break
                    items = self._parse_list(r.text)
                    if not items:
                        break
                    for it in items:
                        by_id.setdefault(it.external_id, it)
                except Exception as exc:
                    log.warning("cargocash list page %s: %s", page, exc)
                    break

            paths = [f"/orders/{slug}" for slug in CFD_NWFD_PFO_REGIONS + _BODY_PATHS]
            for path in paths:
                try:
                    r = await client.get("https://cargocash.ru" + path)
                    if r.status_code != 200:
                        continue
                    for it in self._parse_list(r.text):
                        by_id.setdefault(it.external_id, it)
                except Exception as exc:
                    log.debug("cargocash %s: %s", path, exc)

        out = list(by_id.values())
        log.info("cargocash fetched %s", len(out))
        return out

    def _parse_list(self, html: str) -> list[RawLoad]:
        soup = BeautifulSoup(html, "lxml")
        out: list[RawLoad] = []
        cards = soup.select("a.thinItem[href*='/order/'], a[href*='/order/'].thinItem")
        if not cards:
            # fallback: any order anchors inside listing
            cards = soup.select("a[href*='/order/']")
        seen: set[str] = set()
        for a in cards:
            href = a.get("href") or ""
            m = re.search(r"/order/(\d+)", href)
            if not m:
                continue
            eid = m.group(1)
            if eid in seen:
                continue
            seen.add(eid)
            text = a.get_text(" ", strip=True)
            points = [p.get_text(strip=True) for p in a.select(".route .point")]
            frm = exact_city(points[0]) if len(points) >= 1 else None
            to = exact_city(points[1]) if len(points) >= 2 else None
            if not frm or not to:
                # try "Москва | Шацк" style from title pages later
                rm = re.search(
                    r"([А-ЯЁа-яёA-Za-z][А-ЯЁа-яёA-Za-z.\-\s]{1,40})\s*[—\-–→|/]+\s*([А-ЯЁа-яёA-Za-z][А-ЯЁа-яёA-Za-z.\-\s]{1,40})",
                    text,
                )
                if rm:
                    frm = frm or exact_city(rm.group(1))
                    to = to or exact_city(rm.group(2))
            tonnage = parse_tonnage(text.replace("\xa0", " "))
            vol = None
            vm = re.search(r"(\d+[.,]?\d*)\s*м", text.replace("\xa0", " "))
            if vm:
                try:
                    vol = float(vm.group(1).replace(",", "."))
                except ValueError:
                    vol = None
            price = None
            if "договорн" not in text.lower():
                pm = re.search(r"(\d[\d\s]{2,8})\s*руб", text, re.I)
                if pm:
                    price = re.sub(r"\s+", "", pm.group(1)) + " руб"
            body = f"Есть груз. {frm or '?'} → {to or '?'}. {text}. Ищу машину."[:2000]
            out.append(
                RawLoad(
                    source=self.name,
                    external_id=eid,
                    title=f"{frm or '?'} → {to or '?'} #{eid}",
                    body=body,
                    from_city=frm,
                    to_city=to,
                    tonnage=tonnage,
                    volume_m3=vol,
                    body_type=infer_body(text),
                    price=price,
                    url=f"https://cargocash.ru/order/{eid}",
                    raw={"order_id": eid},
                )
            )
        return out
