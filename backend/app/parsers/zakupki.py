from __future__ import annotations

import re
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import parse_qs, urlencode, urlparse

import certifi
import feedparser
import httpx
from bs4 import BeautifulSoup
from dateutil import parser as date_parser

from app.config import settings
from app.parsers.base import ParsedTender
from app.services.niche import EIS_SEARCH_PASSES


def _ssl_verify() -> bool | str:
    if not settings.http_verify_ssl:
        return False
    return certifi.where()


PRICE_RE = re.compile(
    r"(?:НМЦК|начальн\w*\s+макс\w*\s+цен\w*|цена)\s*[:\-]?\s*"
    r"([\d\s\u00a0]+(?:[.,]\d{1,2})?)\s*(?:руб|₽|RUB)?",
    re.IGNORECASE,
)
REG_NUMBER_RE = re.compile(r"(?:regNumber|reestrNumber)=(\d+)", re.IGNORECASE)
DIGITS_RE = re.compile(r"[^\d.,]")

# Hard transport / TLS failures — do not burn multi-page budget
_HARD_TRANSPORT_MARKERS = (
    "connecterror",
    "connecttimeout",
    "readtimeout",
    "timeout",
    "sslerror",
    "proxyerror",
    "networkerror",
)


def _parse_price(text: str | None) -> float | None:
    if not text:
        return None
    match = PRICE_RE.search(text.replace("\xa0", " "))
    raw = match.group(1) if match else None
    if not raw:
        compact = text.replace("\xa0", " ").replace(" ", "")
        m2 = re.search(r"(\d[\d.,]{3,})", compact)
        raw = m2.group(1) if m2 else None
    if not raw:
        return None
    cleaned = DIGITS_RE.sub("", raw).replace(",", ".")
    try:
        value = float(cleaned)
    except ValueError:
        return None
    return value if value > 0 else None


def _parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        dt = parsedate_to_datetime(value)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except (TypeError, ValueError, IndexError):
        pass
    try:
        dt = date_parser.parse(value, dayfirst=True)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except (TypeError, ValueError, OverflowError):
        return None


def _external_id_from_url(url: str, fallback: str) -> str:
    match = REG_NUMBER_RE.search(url)
    if match:
        return match.group(1)
    path = urlparse(url).path.rstrip("/").split("/")[-1]
    return path or fallback


def _proxy_configured() -> bool:
    return bool(
        (settings.scrape_proxy_url or "").strip()
        or (settings.http_proxy or "").strip()
        or (settings.https_proxy or "").strip()
        or (settings.all_proxy or "").strip()
    )


def _geo_hint_note(base: str) -> str:
    if _proxy_configured():
        return (
            f"{base}. Прокси отвечает, но ЕИС пуст/режет (geo/captcha). "
            "Нужен ISP/residential RU-прокси, не datacenter."
        )
    return f"{base}. Нужен SCRAPE_PROXY_URL (RU ISP/residential прокси)"


class ZakupkiParser:
    """ЕИС zakupki.gov.ru — извещения 44-ФЗ / 223-ФЗ через RSS + HTML fallback."""

    BASE = "https://zakupki.gov.ru/epz/order/extendedsearch/rss.html"
    ALT_RSS = (
        "https://zakupki.gov.ru/epz/order/extendedsearch/rss.html",
        "https://zakupki.gov.ru/epz/order/notice/printForm/searchRss.html",
    )

    def __init__(self, law: str) -> None:
        if law not in {"44", "223"}:
            raise ValueError("law must be 44 or 223")
        self.law = law
        self.source = f"zakupki_{law}"
        self.display_name = f"ЕИС · {law}-ФЗ"
        self.public_listing = True
        self.requires_api = False
        self.last_fetch_note: str | None = None
        self.unavailable_reason: str | None = None

    def _rss_url(
        self,
        page: int = 1,
        base: str | None = None,
        search_string: str | None = None,
    ) -> str:
        params = {
            "morphology": "on",
            "search-filter": "Дате размещения",
            "pageNumber": str(page),
            "sortDirection": "false",
            "recordsPerPage": "_50",
            "showLotsInfoHidden": "false",
            "sortBy": "PUBLISH_DATE",
            f"fz{self.law}": "on",
            "af": "on",
            "ca": "on",
            "pc": "on",
            "pa": "on",
            "currencyIdGeneral": "-1",
        }
        if search_string:
            params["searchString"] = search_string
        root = base or self.BASE
        return f"{root}?{urlencode(params)}"

    def _html_url(self, page: int = 1, search_string: str | None = None) -> str:
        params = parse_qs(urlparse(self._rss_url(page, search_string=search_string)).query)
        flat = {k: v[0] for k, v in params.items()}
        return (
            "https://zakupki.gov.ru/epz/order/extendedsearch/results.html?"
            + urlencode(flat)
        )

    def _page_budget(self, hard_transport: bool) -> int:
        if hard_transport:
            return 1
        # Deeper crawl when proxy/path works
        if _proxy_configured():
            return min(10, max(5, settings.eis_max_pages))
        return min(3, max(1, settings.eis_max_pages))

    async def fetch(self) -> list[ParsedTender]:
        headers = {
            "Accept": "application/rss+xml, application/xml, text/xml, */*;q=0.8",
            "Accept-Language": "ru-RU,ru;q=0.9,en;q=0.5",
        }
        # Probe + niche passes via RSS
        tenders, hard_transport = await self._from_rss_cached(headers)
        if tenders:
            self.last_fetch_note = None
            return tenders

        note = (self.last_fetch_note or "").lower()
        hard_transport = hard_transport or any(x in note for x in _HARD_TRANSPORT_MARKERS)
        if hard_transport:
            if not self.last_fetch_note:
                self.last_fetch_note = _geo_hint_note(
                    f"ЕИС {self.law}-ФЗ: сетевая ошибка / таймаут"
                )
            return []

        html_items = await self._from_html(hard_transport=False)
        if html_items:
            self.last_fetch_note = None
            return html_items

        if not self.last_fetch_note:
            self.last_fetch_note = _geo_hint_note(
                f"ЕИС {self.law}-ФЗ недоступен (SSL/geo/captcha)"
            )
        elif "geo" in (self.last_fetch_note or "").lower() or "captcha" in (
            self.last_fetch_note or ""
        ).lower():
            self.last_fetch_note = _geo_hint_note(self.last_fetch_note)
        return []

    async def _from_rss(self, client: httpx.AsyncClient) -> list[ParsedTender]:
        """Legacy path kept for tests; prefer _from_rss_cached in production."""
        items: list[ParsedTender] = []
        for page in (1, 2):
            try:
                response = await client.get(self._rss_url(page))
            except httpx.HTTPError:
                continue
            if response.status_code != 200:
                continue
            feed = feedparser.parse(response.text)
            items.extend(self._parse_rss_feed(feed))
            if not feed.entries:
                break
        return self._dedupe(items)

    def _parse_rss_feed(self, feed) -> list[ParsedTender]:
        items: list[ParsedTender] = []
        for entry in feed.entries:
            link = getattr(entry, "link", "") or ""
            title = (getattr(entry, "title", None) or "").strip()
            if not title or not link:
                continue
            summary = getattr(entry, "summary", None) or getattr(entry, "description", None) or ""
            published = _parse_datetime(getattr(entry, "published", None) or getattr(entry, "updated", None))
            customer = None
            if hasattr(entry, "author"):
                customer = entry.author
            elif "заказчик" in summary.lower():
                m = re.search(r"Заказчик\s*[:\-]\s*(.+?)(?:<br|/p>|\n|$)", summary, re.I)
                if m:
                    customer = BeautifulSoup(m.group(1), "lxml").get_text(" ", strip=True)

            clean_desc = BeautifulSoup(summary, "lxml").get_text(" ", strip=True)
            items.append(
                ParsedTender(
                    external_id=_external_id_from_url(link, title[:40]),
                    source=self.source,
                    law=f"{self.law}-ФЗ",
                    title=BeautifulSoup(title, "lxml").get_text(" ", strip=True),
                    customer=customer,
                    price=_parse_price(clean_desc),
                    url=link,
                    description=clean_desc[:2000] or None,
                    published_at=published,
                    status="Размещено",
                )
            )
        return items

    @staticmethod
    def _dedupe(items: list[ParsedTender]) -> list[ParsedTender]:
        seen: set[str] = set()
        unique: list[ParsedTender] = []
        for item in items:
            if item.external_id in seen:
                continue
            seen.add(item.external_id)
            unique.append(item)
        return unique

    async def _fetch_rss_page(
        self,
        url: str,
        headers: dict[str, str],
    ) -> tuple[list[ParsedTender], str | None, bool]:
        """Returns (items, note, hard_transport)."""
        from app.services.http_client import cached_get

        try:
            response = await cached_get(url, headers=headers)
        except httpx.HTTPError as exc:
            name = type(exc).__name__
            hard = name.lower() in {m.replace("error", "error") for m in _HARD_TRANSPORT_MARKERS} or any(
                m in name.lower() for m in _HARD_TRANSPORT_MARKERS
            )
            return [], f"RSS {name}", hard
        if response.status_code != 200:
            note = f"RSS HTTP {response.status_code}"
            if response.status_code in {403, 429, 451}:
                note += " (geo/captcha?)"
            return [], note, False
        low = response.text.lower()
        if "<item" not in low and "<entry" not in low:
            hint = "geo/captcha?" if ("captcha" in low or "доступ ограничен" in low or len(response.text) < 800) else "пусто"
            return [], f"RSS без item ({hint})", False
        feed = feedparser.parse(response.text)
        return self._parse_rss_feed(feed), None, False

    async def _from_rss_cached(self, headers: dict[str, str]) -> tuple[list[ParsedTender], bool]:
        items: list[ParsedTender] = []
        notes: list[str] = []
        hard_transport = False

        # Probe without searchString first (1 page) to detect transport health
        probe_url = self._rss_url(1)
        probe_items, probe_note, probe_hard = await self._fetch_rss_page(probe_url, headers)
        if probe_hard:
            self.last_fetch_note = probe_note or "RSS transport fail"
            return [], True
        if probe_items:
            items.extend(probe_items)
        elif probe_note:
            notes.append(probe_note)

        pages = self._page_budget(hard_transport=False)
        passes = list(EIS_SEARCH_PASSES)

        for term in passes:
            for page in range(1, pages + 1):
                url = self._rss_url(page, search_string=term)
                page_items, note, hard = await self._fetch_rss_page(url, headers)
                if hard:
                    hard_transport = True
                    if note:
                        notes.append(f"{term}: {note}")
                    break
                if note and not page_items:
                    notes.append(f"{term} p{page}: {note}")
                    # Soft fail on page 1 of a pass — try next term; stop paging this term
                    break
                if not page_items:
                    break
                items.extend(page_items)
            if hard_transport:
                break

        if notes and not items:
            joined = "; ".join(notes[:4])
            if any(x in joined.lower() for x in ("geo", "captcha", "без item", "403", "451")):
                self.last_fetch_note = _geo_hint_note(joined)
            else:
                self.last_fetch_note = joined
        return self._dedupe(items), hard_transport

    async def _from_html(self, hard_transport: bool = False) -> list[ParsedTender]:
        from app.services.http_client import cached_get

        headers = {
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "ru-RU,ru;q=0.9,en;q=0.5",
        }
        items: list[ParsedTender] = []
        notes: list[str] = []
        pages = self._page_budget(hard_transport)
        passes = [None, *EIS_SEARCH_PASSES]

        for term in passes:
            for page in range(1, pages + 1):
                try:
                    response = await cached_get(
                        self._html_url(page, search_string=term),
                        headers=headers,
                    )
                except httpx.HTTPError as exc:
                    notes.append(f"HTML {type(exc).__name__}")
                    if any(m in type(exc).__name__.lower() for m in _HARD_TRANSPORT_MARKERS):
                        if notes and not items and not self.last_fetch_note:
                            self.last_fetch_note = "; ".join(notes[:3])
                        return self._dedupe(items)
                    break
                if response.status_code != 200:
                    notes.append(f"HTML HTTP {response.status_code}")
                    if response.status_code in {403, 429, 451}:
                        notes[-1] += " (geo/captcha?)"
                    break
                soup = BeautifulSoup(response.text, "lxml")
                blocks = soup.select(".search-registry-entry-block") or soup.select(
                    "div.registry-entry__form"
                )
                if not blocks:
                    low = response.text.lower()
                    if "captcha" in low or "доступ ограничен" in low:
                        notes.append("HTML captcha/geo")
                    break
                for block in blocks:
                    link_el = block.select_one("a[href*='regNumber'], a[href*='notice']")
                    if not link_el:
                        continue
                    href = link_el.get("href", "")
                    if href.startswith("/"):
                        href = "https://zakupki.gov.ru" + href
                    title = link_el.get_text(" ", strip=True)
                    if not title:
                        continue
                    text = block.get_text(" ", strip=True)
                    customer_el = block.select_one(".registry-entry__body-href a") or block.select_one(
                        ".registry-entry__body-value"
                    )
                    customer = customer_el.get_text(" ", strip=True) if customer_el else None
                    price_el = block.select_one(".price-block__value") or block.select_one(".cost")
                    price = _parse_price(price_el.get_text(" ", strip=True) if price_el else text)
                    date_el = block.select_one(".data-block__value")
                    published = _parse_datetime(date_el.get_text(" ", strip=True) if date_el else None)
                    items.append(
                        ParsedTender(
                            external_id=_external_id_from_url(href, title[:40]),
                            source=self.source,
                            law=f"{self.law}-ФЗ",
                            title=title,
                            customer=customer,
                            price=price,
                            url=href,
                            description=text[:2000],
                            published_at=published,
                            status="Размещено",
                        )
                    )
            if hard_transport:
                break

        if notes and not items and not self.last_fetch_note:
            joined = "; ".join(notes[:3])
            if any(x in joined.lower() for x in ("geo", "captcha", "403", "451")):
                self.last_fetch_note = _geo_hint_note(joined)
            else:
                self.last_fetch_note = joined
        return self._dedupe(items)
