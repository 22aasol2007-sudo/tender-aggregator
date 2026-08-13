"""InGruz public cargo search pages."""

from __future__ import annotations

import logging
import re

import httpx
from bs4 import BeautifulSoup

from app import config
from app.models import RawLoad
from app.scrapers.board_common import exact_city, infer_body, parse_tonnage

log = logging.getLogger("scraper.ingruz")


class InGruzScraper:
    name = "ingruz"

    async def fetch(self) -> list[RawLoad]:
        headers = {
            "User-Agent": config.USER_AGENT,
            "Accept-Language": "ru-RU,ru;q=0.9",
        }
        by_id: dict[str, RawLoad] = {}
        urls = [
            "https://www.ingruz.ru/poisk-gruzov-dlya-perevozki",
            "https://www.ingruz.ru/cargo/index",
            "https://www.ingruz.ru/",
        ]
        async with httpx.AsyncClient(timeout=35.0, headers=headers, follow_redirects=True) as client:
            detail_paths: list[str] = []
            for url in urls:
                try:
                    r = await client.get(url)
                    if r.status_code != 200:
                        continue
                    detail_paths.extend(
                        re.findall(r'href="(/poisk-gruzov-dlya-perevozki/gruz-[^"]+)"', r.text)
                    )
                    for it in self._parse_list(r.text):
                        by_id.setdefault(it.external_id, it)
                except Exception as exc:
                    log.warning("ingruz %s: %s", url, exc)
            for path in list(dict.fromkeys(detail_paths)):
                try:
                    r = await client.get("https://www.ingruz.ru" + path)
                    if r.status_code != 200:
                        continue
                    it = self._parse_detail(r.text, path)
                    if it:
                        by_id[it.external_id] = it
                except Exception as exc:
                    log.debug("ingruz detail %s: %s", path, exc)
        out = list(by_id.values())
        log.info("ingruz fetched %s", len(out))
        return out

    def _parse_list(self, html: str) -> list[RawLoad]:
        out: list[RawLoad] = []
        for path in re.findall(r'href="(/poisk-gruzov-dlya-perevozki/gruz-[^"]+)"', html):
            m = re.search(r"-(\d+)$", path)
            eid = m.group(1) if m else path
            slug = path.rsplit("/", 1)[-1]
            parts = slug.replace("gruz-", "").rsplit("-", 1)[0].split("-")
            frm = to = None
            if len(parts) >= 2:
                mid = len(parts) // 2
                frm = exact_city(" ".join(parts[:mid]).replace("_", " "))
                to = exact_city(" ".join(parts[mid:]).replace("_", " "))
            out.append(
                RawLoad(
                    source=self.name,
                    external_id=str(eid),
                    title=f"{frm or '?'} → {to or '?'} #{eid}",
                    body=f"Есть груз. {frm or '?'} → {to or '?'}. Ищу машину.",
                    from_city=frm,
                    to_city=to,
                    url="https://www.ingruz.ru" + path,
                    raw={"path": path},
                )
            )
        return out

    def _parse_detail(self, html: str, path: str) -> RawLoad | None:
        soup = BeautifulSoup(html, "lxml")
        text = soup.get_text(" ", strip=True)
        m = re.search(r"-(\d+)$", path)
        eid = m.group(1) if m else path
        title = (soup.title.string or "") if soup.title else ""
        frm = to = None
        rm = re.search(
            r"из\s+г\.?\s*([А-ЯЁа-яёA-Za-z.\-\s]{2,40}?)\s+в\s+([А-ЯЁа-яёA-Za-z.\-\s]{2,40}?)(?:\s|$|,|\.)",
            title,
            re.I,
        )
        if not rm:
            rm = re.search(
                r"([А-ЯЁа-яё][А-ЯЁа-яё.\-\s]{1,40})\s*[—\-–→]+\s*([А-ЯЁа-яё][А-ЯЁа-яё.\-\s]{1,40})",
                title + " " + text[:500],
            )
        if rm:
            frm, to = exact_city(rm.group(1)), exact_city(rm.group(2))
        body = f"Есть груз. {frm or '?'} → {to or '?'}. {text[:900]}. Ищу машину."[:2000]
        return RawLoad(
            source=self.name,
            external_id=str(eid),
            title=f"{frm or '?'} → {to or '?'} #{eid}",
            body=body,
            from_city=frm,
            to_city=to,
            tonnage=parse_tonnage(text),
            body_type=infer_body(text),
            url="https://www.ingruz.ru" + path,
            raw={"path": path},
        )
