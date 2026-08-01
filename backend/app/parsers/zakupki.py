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


class ZakupkiParser:
    """ЕИС zakupki.gov.ru — извещения 44-ФЗ / 223-ФЗ через RSS + HTML fallback."""

    BASE = "https://zakupki.gov.ru/epz/order/extendedsearch/rss.html"
    # Open RSS mirrors / alternate entry points when primary geo-blocks from EU/US
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

    def _rss_url(self, page: int = 1, base: str | None = None) -> str:
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
        root = base or self.BASE
        return f"{root}?{urlencode(params)}"

    def _html_url(self, page: int = 1) -> str:
        params = parse_qs(urlparse(self._rss_url(page)).query)
        flat = {k: v[0] for k, v in params.items()}
        return (
            "https://zakupki.gov.ru/epz/order/extendedsearch/results.html?"
            + urlencode(flat)
        )

    async def fetch(self) -> list[ParsedTender]:
        headers = {
            "Accept": "application/rss+xml, application/xml, text/xml, */*;q=0.8",
            "Accept-Language": "ru-RU,ru;q=0.9,en;q=0.5",
        }
        # RSS first (works better from abroad than full HTML search UI)
        tenders = await self._from_rss_cached(headers)
        if tenders:
            self.last_fetch_note = None
            return tenders
        # Skip HTML only on hard transport failures. Soft RSS bodies
        # ("без item", HTTP 403, captcha HTML) may still parse via HTML + RU proxy.
        note = (self.last_fetch_note or "").lower()
        hard_transport = any(
            x in note
            for x in (
                "connecterror",
                "connecttimeout",
                "readtimeout",
                "timeout",
                "sslerror",
                "proxyerror",
                "networkerror",
            )
        )
        if hard_transport:
            return []
        html_items = await self._from_html()
        if html_items:
            self.last_fetch_note = None
            return html_items
        if not self.last_fetch_note:
            self.last_fetch_note = (
                f"ЕИС {self.law}-ФЗ недоступен из-за рубежа (SSL/geo). "
                "Нужен SCRAPE_PROXY_URL (RU-прокси)"
            )
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

    async def _from_rss_cached(self, headers: dict[str, str]) -> list[ParsedTender]:
        from app.services.http_client import cached_get

        items: list[ParsedTender] = []
        notes: list[str] = []
        # One RSS page only — second page burns budget when EIS is geo-blocked from AMS
        for page in (1,):
            url = self._rss_url(page)
            try:
                response = await cached_get(url, headers=headers)
            except httpx.HTTPError as exc:
                notes.append(f"RSS {type(exc).__name__}")
                break
            if response.status_code != 200:
                notes.append(f"RSS HTTP {response.status_code}")
                break
            if "<item" not in response.text.lower() and "<entry" not in response.text.lower():
                notes.append("RSS без item (geo/captcha?)")
                break
            feed = feedparser.parse(response.text)
            page_items = self._parse_rss_feed(feed)
            items.extend(page_items)
        if notes and not items:
            self.last_fetch_note = "; ".join(notes[:3])
        return self._dedupe(items)

    async def _from_html(self) -> list[ParsedTender]:
        from app.services.http_client import cached_get

        headers = {
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "ru-RU,ru;q=0.9,en;q=0.5",
        }
        items: list[ParsedTender] = []
        notes: list[str] = []
        for page in (1, 2):
            try:
                response = await cached_get(self._html_url(page), headers=headers)
            except httpx.HTTPError as exc:
                notes.append(f"HTML {type(exc).__name__}")
                break
            if response.status_code != 200:
                notes.append(f"HTML HTTP {response.status_code}")
                break
            soup = BeautifulSoup(response.text, "lxml")
            blocks = soup.select(".search-registry-entry-block") or soup.select(
                "div.registry-entry__form"
            )
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
                price_el = block.select_one(".price-block__value") or block.select_one(
                    ".cost"
                )
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
            if not blocks:
                break
        if notes and not items and not self.last_fetch_note:
            self.last_fetch_note = "; ".join(notes[:3])
        seen: set[str] = set()
        unique: list[ParsedTender] = []
        for item in items:
            if item.external_id in seen:
                continue
            seen.add(item.external_id)
            unique.append(item)
        return unique
