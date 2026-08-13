"""Perevozka24 public load board scraper."""

from __future__ import annotations

import logging
import re
from typing import Iterable

import httpx
from bs4 import BeautifulSoup, Tag

from app import config
from app.models import RawLoad
from app.scrapers.board_common import parse_posted_at_ru
from app.parse import CITY_ALIASES

log = logging.getLogger("scraper.perevozka24")

# Main feed + body/tonnage + ЦФО / СЗФО / ПФО region pages.
DEFAULT_PATHS: list[str] = [
    "/poisk-gruzov",
    "/poisk-gruzov/fura",
    "/poisk-gruzov/20-tonn",
    "/poisk-gruzov/10-tonn",
    "/poisk-gruzov/5-tonn",
    "/poisk-gruzov/gazel",
    "/poisk-gruzov/furgon",
    "/poisk-gruzov/bortovoi-gruzovik",
    "/poisk-gruzov/izotermicheskiy-gruzovik",
    "/poisk-gruzov/avtopoezd",
    # ЦФО
    "/poisk-gruzov/moskva",
    "/poisk-gruzov/moskovskaya-oblast",
    "/poisk-gruzov/belgorodskaya-oblast",
    "/poisk-gruzov/bryanskaya-oblast",
    "/poisk-gruzov/vladimirskaya-oblast",
    "/poisk-gruzov/voronezhskaya-oblast",
    "/poisk-gruzov/ivanovskaya-oblast",
    "/poisk-gruzov/kaluzhskaya-oblast",
    "/poisk-gruzov/kostromskaya-oblast",
    "/poisk-gruzov/kurskaya-oblast",
    "/poisk-gruzov/lipetskaya-oblast",
    "/poisk-gruzov/orlovskaya-oblast",
    "/poisk-gruzov/ryazanskaya-oblast",
    "/poisk-gruzov/smolenskaya-oblast",
    "/poisk-gruzov/tambovskaya-oblast",
    "/poisk-gruzov/tverskaya-oblast",
    "/poisk-gruzov/tulskaya-oblast",
    "/poisk-gruzov/yaroslavskaya-oblast",
    # СЗФО
    "/poisk-gruzov/sankt-peterburg",
    "/poisk-gruzov/leningradskaya-oblast",
    "/poisk-gruzov/arhangelskaya-oblast",
    "/poisk-gruzov/vologodskaya-oblast",
    "/poisk-gruzov/kaliningradskaya-oblast",
    "/poisk-gruzov/murmanskaya-oblast",
    "/poisk-gruzov/novgorodskaya-oblast",
    "/poisk-gruzov/pskovskaya-oblast",
    "/poisk-gruzov/kareliya",
    "/poisk-gruzov/komi",
    # ПФО
    "/poisk-gruzov/nizhegorodskaya-oblast",
    "/poisk-gruzov/kirovskaya-oblast",
    "/poisk-gruzov/samarskaya-oblast",
    "/poisk-gruzov/saratovskaya-oblast",
    "/poisk-gruzov/ulyanovskaya-oblast",
    "/poisk-gruzov/penzenskaya-oblast",
    "/poisk-gruzov/orenburgskaya-oblast",
    "/poisk-gruzov/permskiy-kray",
    "/poisk-gruzov/bashkiriya",
    "/poisk-gruzov/tatarstan",
    "/poisk-gruzov/udmurtiya",
    "/poisk-gruzov/chuvashiya",
    "/poisk-gruzov/mordoviya",
    "/poisk-gruzov/mariy-el",
]

_BODY_MAP = (
    ("реф", "reefer"),
    ("холодиль", "reefer"),
    ("изотерм", "isotherm"),
    ("тент", "tent"),
    ("штор", "tent"),
    ("борт", "board"),
    ("фургон", "box"),
    ("цельнометалл", "box"),
)


def _city_from_label(raw: str | None) -> str | None:
    if not raw:
        return None
    # "Новоалександровск (Ставропольский край)" -> city part
    name = raw.split("(")[0].strip(" \t\r\n,.-")
    if not name:
        return None
    # Exact alias only — weak substring canon maps Новоалександровск→Александров
    key = name.lower().replace("ё", "е")
    for alias, canon in CITY_ALIASES.items():
        if alias.replace("ё", "е") == key:
            return canon
    return key


def _infer_body(text: str) -> str | None:
    low = text.lower()
    for key, body in _BODY_MAP:
        if key in low:
            return body
    return None


def _offer_id(el: Tag, text: str) -> str | None:
    m = re.search(r"№\s*(\d{5,})", text)
    if m:
        return m.group(1)
    vb = el.select_one("[data-id]")
    if vb and vb.get("data-id"):
        return str(vb.get("data-id"))
    m = re.search(r"offer[_-]?id[=-](\d{5,})", str(el), re.I)
    if m:
        return m.group(1)
    m = re.search(r"full-image-offer-id-(\d{5,})", str(el))
    if m:
        return m.group(1)
    return None


def _route_cities(el: Tag, text: str) -> tuple[str | None, str | None]:
    route = el.select_one(".route, span.route, .offer-item-info.route")
    if route:
        raw = route.get_text(" ", strip=True)
        parts = re.split(r"\s*[→\-–—]\s*", raw, maxsplit=1)
        if len(parts) == 2:
            return _city_from_label(parts[0]), _city_from_label(parts[1])
    m = re.search(
        r"([А-ЯЁа-яёA-Za-z][А-ЯЁа-яёA-Za-z.\-\s]{1,40}?)\s*(?:\([^)]*\))?\s*[→\-–—]\s*"
        r"([А-ЯЁа-яёA-Za-z][А-ЯЁа-яёA-Za-z.\-\s]{1,40}?)\s*(?:\([^)]*\))?",
        text,
    )
    if m:
        return _city_from_label(m.group(1)), _city_from_label(m.group(2))
    return None, None


class Perevozka24Scraper:
    """HTML scrape of public search pages (SSR cards with stable offer ids)."""

    name = "perevozka24"

    def __init__(self, paths: Iterable[str] | None = None) -> None:
        self.paths = list(paths) if paths is not None else list(DEFAULT_PATHS)

    async def fetch(self) -> list[RawLoad]:
        headers = {
            "User-Agent": config.USER_AGENT,
            "Accept": "text/html,application/xhtml+xml",
            "Accept-Language": "ru-RU,ru;q=0.9",
        }
        hosts = ("https://perevozka24.com", "https://perevozka24.ru")
        by_id: dict[str, RawLoad] = {}
        async with httpx.AsyncClient(timeout=40.0, headers=headers, follow_redirects=True) as client:
            host_ok: str | None = None
            for host in hosts:
                try:
                    probe = await client.get(f"{host}/poisk-gruzov")
                    probe.raise_for_status()
                    host_ok = str(probe.url).rstrip("/").rsplit("/poisk-gruzov", 1)[0] or host
                    for item in self._parse_html(probe.text, host_ok):
                        by_id[item.external_id] = item
                    break
                except Exception as exc:
                    log.warning("p24 probe %s: %s", host, exc)
            if not host_ok:
                log.info("perevozka24 fetched 0")
                return []

            for path in self.paths:
                if path.rstrip("/") in {"/poisk-gruzov", "poisk-gruzov"}:
                    continue  # already fetched as probe
                url = host_ok + (path if path.startswith("/") else "/" + path)
                try:
                    r = await client.get(url)
                    if r.status_code != 200:
                        log.debug("p24 %s status %s", path, r.status_code)
                        continue
                    for item in self._parse_html(r.text, host_ok):
                        by_id.setdefault(item.external_id, item)
                except Exception as exc:
                    log.warning("p24 %s: %s", path, exc)

        out = list(by_id.values())
        log.info("perevozka24 fetched %s unique offers from %s pages", len(out), len(self.paths))
        return out

    def _parse_html(self, html: str, base_url: str) -> list[RawLoad]:
        soup = BeautifulSoup(html, "lxml")
        out: list[RawLoad] = []
        seen: set[str] = set()
        cards = soup.select(".offer-item-wrapper")
        if not cards:
            cards = soup.select(".offer_main")
        for el in cards:
            text = el.get_text(" ", strip=True)
            if len(text) < 40:
                continue
            cls = " ".join(el.get("class") or []).lower()
            html_snip = str(el)[:800].lower()
            if any(x in cls for x in ("completed", "archive", "closed", "finished", "done")):
                continue
            if re.search(r"data-status=[\"'](?:completed|closed|archive|done)", html_snip):
                continue
            if re.search(r"\b(заверш[её]н|в архиве|снят с публикации)\b", text.lower()):
                continue
            eid = _offer_id(el, text)
            if not eid or eid in seen:
                continue
            seen.add(eid)

            frm, to = _route_cities(el, text)
            tonnage = None
            tm = re.search(r"(?:ВЕС|вес)\s*(\d+[.,]?\d*)\s*т", text, re.I)
            if not tm:
                tm = re.search(r"до\s+(\d+[.,]?\d*)\s*тонн", text, re.I)
            if not tm:
                tm = re.search(r"(\d+[.,]?\d*)\s*т(?:онн)?\b", text, re.I)
            if tm:
                try:
                    tonnage = float(tm.group(1).replace(",", "."))
                except ValueError:
                    tonnage = None

            price = None
            pm = re.search(r"Бюджет\s*:\s*([\d\s]+)\s*руб", text, re.I)
            if pm:
                price = re.sub(r"\s+", "", pm.group(1)) + " руб"

            body_type = _infer_body(text)
            posted_at = parse_posted_at_ru(text)
            # Prefer dedicated datetime node if present
            for sel in (".date", ".offer-date", ".time", "time", "[datetime]"):
                node = el.select_one(sel)
                if not node:
                    continue
                candidate = parse_posted_at_ru(node.get_text(" ", strip=True))
                if candidate:
                    posted_at = candidate
                    break
            # Make text look like a shipper post for scoring/kind detection
            body = (
                f"Есть груз. {frm or '?'} → {to or '?'}. {text}. Ищу машину."
            )[:2000]
            out.append(
                RawLoad(
                    source=self.name,
                    external_id=eid,
                    title=f"{frm or '?'} → {to or '?'} #{eid}",
                    body=body,
                    from_city=frm,
                    to_city=to,
                    tonnage=tonnage,
                    body_type=body_type,
                    price=price,
                    url=f"{base_url}/poisk-gruzov?offer_id={eid}",
                    posted_at=posted_at,
                    raw={"offer_id": eid, "posted_at": posted_at},
                )
            )
        return out
