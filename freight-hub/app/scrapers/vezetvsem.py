"""Везёт Всем — public listing pages."""

from __future__ import annotations

import logging
import re

import httpx
from bs4 import BeautifulSoup

from app import config
from app.models import RawLoad
from app.scrapers.board_common import exact_city, infer_body, parse_tonnage

log = logging.getLogger("scraper.vezetvsem")

LIST_URLS = [
    "https://www.vezetvsem.ru/listing/all",
    "https://www.vezetvsem.ru/listing/moskva",
    "https://spb.vezetvsem.ru/listing/all",
    "https://nnov.vezetvsem.ru/listing/all",
    "https://kazan.vezetvsem.ru/listing/all",
    "https://samara.vezetvsem.ru/listing/all",
    "https://ufa.vezetvsem.ru/listing/all",
    "https://perm.vezetvsem.ru/listing/all",
    "https://www.vezetvsem.ru/listing/all/dogruz",
    "https://www.vezetvsem.ru/listing/all/stroitelnye_gruzy_i_oborudovanie",
    "https://www.vezetvsem.ru/listing/all/produkty_pitanija",
]


class VezetVsemScraper:
    name = "vezetvsem"

    def __init__(self, max_pages: int = 12) -> None:
        self.max_pages = max_pages

    async def fetch(self) -> list[RawLoad]:
        headers = {
            "User-Agent": config.USER_AGENT,
            "Accept-Language": "ru-RU,ru;q=0.9",
            "Accept": "text/html,application/xhtml+xml",
        }
        by_id: dict[str, RawLoad] = {}
        async with httpx.AsyncClient(timeout=45.0, headers=headers, follow_redirects=True) as client:
            for base in LIST_URLS:
                for page in range(1, self.max_pages + 1):
                    url = base if page == 1 else f"{base}{'&' if '?' in base else '?'}page={page}"
                    try:
                        r = await client.get(url)
                        if r.status_code != 200:
                            break
                        items = self._parse(r.text)
                        if not items:
                            break
                        new = 0
                        for it in items:
                            if it.external_id not in by_id:
                                by_id[it.external_id] = it
                                new += 1
                        if new == 0 and page > 1:
                            break
                    except Exception as exc:
                        log.warning("vezetvsem %s: %s", url, exc)
                        break
        out = list(by_id.values())
        log.info("vezetvsem fetched %s", len(out))
        return out

    def _parse(self, html: str) -> list[RawLoad]:
        soup = BeautifulSoup(html, "lxml")
        out: list[RawLoad] = []
        for el in soup.select(".x-order-main-part[data-id], div.x-order-main-part"):
            eid = el.get("data-id") or ""
            if not eid:
                m = re.search(r"x-order-(\d+)", el.get("id") or "")
                eid = m.group(1) if m else ""
            if not eid:
                continue
            frm_el = el.select_one(".from-town-name")
            to_el = el.select_one(".to-town-name")
            frm = exact_city(frm_el.get_text(strip=True)) if frm_el else None
            to = exact_city(to_el.get_text(strip=True)) if to_el else None
            title_el = el.select_one("a.order_info .top_info, .order_info .top_info, .top_info")
            cargo = title_el.get_text(strip=True) if title_el else "Груз"
            text = el.get_text(" ", strip=True).replace("\xa0", " ")
            tonnage = parse_tonnage(text)
            # weight often like "130 кг"
            if tonnage is None:
                km = re.search(r"(\d+[.,]?\d*)\s*кг", text, re.I)
                if km:
                    try:
                        tonnage = float(km.group(1).replace(",", ".")) / 1000.0
                    except ValueError:
                        pass
            vol = None
            vm = re.search(r"(\d+[.,]?\d*)\s*м", text)
            if vm:
                try:
                    vol = float(vm.group(1).replace(",", "."))
                except ValueError:
                    pass
            href = None
            a = el.select_one("a.x-order-link[href], a.order_info[href]")
            if a and a.get("href"):
                href = a["href"]
                if href.startswith("//"):
                    href = "https:" + href
                elif href.startswith("/"):
                    href = "https://www.vezetvsem.ru" + href
            body = (
                f"Есть груз: {cargo}. {frm or '?'} → {to or '?'}. {text}. Ищу машину."
            )[:2000]
            out.append(
                RawLoad(
                    source=self.name,
                    external_id=str(eid),
                    title=f"{frm or '?'} → {to or '?'} #{eid}",
                    body=body,
                    from_city=frm,
                    to_city=to,
                    tonnage=tonnage,
                    volume_m3=vol,
                    body_type=infer_body(text + " " + cargo),
                    url=href or f"https://www.vezetvsem.ru/listing/all",
                    raw={"order_id": eid, "cargo": cargo},
                )
            )
        return out
