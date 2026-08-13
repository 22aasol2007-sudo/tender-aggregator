"""Автодиспетчер.Ру — public consignor cargo list."""

from __future__ import annotations

import logging
import re

import httpx
from bs4 import BeautifulSoup

from app import config
from app.models import RawLoad
from app.scrapers.board_common import exact_city, infer_body, parse_tonnage

log = logging.getLogger("scraper.avtodispetcher")


class AvtodispetcherScraper:
    name = "avtodispetcher"

    def __init__(self, max_pages: int = 8) -> None:
        self.max_pages = max_pages

    async def fetch(self) -> list[RawLoad]:
        headers = {
            "User-Agent": config.USER_AGENT,
            "Accept-Language": "ru-RU,ru;q=0.9",
        }
        by_id: dict[str, RawLoad] = {}
        urls = ["https://www.avtodispetcher.ru/consignor/"]
        urls += [f"https://www.avtodispetcher.ru/consignor/page-{p}" for p in range(2, self.max_pages + 1)]
        # city filters for ЦФО / СЗФО / ПФО hubs
        for city in (
            "Москва",
            "Санкт-Петербург",
            "Тверь",
            "Тула",
            "Калуга",
            "Рязань",
            "Владимир",
            "Ярославль",
            "Воронеж",
            "Нижний Новгород",
            "Казань",
            "Самара",
            "Уфа",
            "Пермь",
            "Киров",
            "Пенза",
            "Саратов",
            "Ульяновск",
            "Вологда",
            "Архангельск",
            "Мурманск",
            "Калининград",
            "Псков",
            "Великий Новгород",
        ):
            urls.append(f"https://www.avtodispetcher.ru/consignor/?f={city}")

        async with httpx.AsyncClient(timeout=40.0, headers=headers, follow_redirects=True) as client:
            for url in urls:
                try:
                    r = await client.get(url)
                    if r.status_code != 200:
                        continue
                    for it in self._parse(r.text):
                        by_id.setdefault(it.external_id, it)
                except Exception as exc:
                    log.warning("avtodispetcher %s: %s", url, exc)
        out = list(by_id.values())
        log.info("avtodispetcher fetched %s", len(out))
        return out

    def _parse(self, html: str) -> list[RawLoad]:
        soup = BeautifulSoup(html, "lxml")
        out: list[RawLoad] = []
        for tr in soup.select("table tr.data_row, table tr"):
            link = tr.select_one("a[href*='/consignor/'][href$='.html']")
            if not link:
                continue
            href = link.get("href") or ""
            m = re.search(r"/consignor/(\d+)\.html", href)
            if not m:
                continue
            eid = m.group(1)
            tds = tr.select("td")
            frm = to = None
            if len(tds) >= 2:
                frm = self._cell_city(tds[0])
                to = self._cell_city(tds[1])
            text = tr.get_text(" ", strip=True).replace("\xa0", " ")
            tonnage = parse_tonnage(text)
            vol = None
            vm = re.search(r"(\d+[.,]?\d*)\s*м3", text, re.I)
            if vm:
                try:
                    vol = float(vm.group(1).replace(",", "."))
                except ValueError:
                    pass
            price = None
            pm = re.search(r"(\d[\d\s]{2,8})\s*руб", text, re.I)
            if pm:
                price = re.sub(r"\s+", "", pm.group(1)) + " руб"
            url = href if href.startswith("http") else "https://www.avtodispetcher.ru" + href
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
                    url=url,
                    raw={"offer_id": eid},
                )
            )
        uniq: dict[str, RawLoad] = {}
        for it in out:
            uniq.setdefault(it.external_id, it)
        return list(uniq.values())

    @staticmethod
    def _cell_city(td) -> str | None:
        a = td.select_one("a")
        node = a or td
        # drop region/country suffixes
        for span in node.select("span.country, .distance"):
            span.decompose()
        raw = node.get_text(" ", strip=True)
        raw = re.split(r"\d+\s*км", raw)[0].strip(" ,|")
        return exact_city(raw)