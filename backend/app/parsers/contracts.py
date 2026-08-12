from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from urllib.parse import parse_qs, urlencode, urlparse

import feedparser
import httpx
from bs4 import BeautifulSoup
from dateutil import parser as date_parser

from app.config import settings


@dataclass
class ParsedContract:
    external_id: str
    source: str
    title: str
    url: str
    law: str | None = None
    purchase_number: str | None = None
    customer: str | None = None
    customer_inn: str | None = None
    supplier_name: str | None = None
    supplier_inn: str | None = None
    region: str | None = None
    price: float | None = None
    nmck: float | None = None
    currency: str = "RUB"
    status: str | None = None
    okpd2: str | None = None
    description: str | None = None
    signed_at: datetime | None = None
    published_at: datetime | None = None
    extra: dict = field(default_factory=dict)


PRICE_RE = re.compile(
    r"(?:цена\s+контракта|цена\s+договора|сумма\s+контракта|стоимость|"
    r"цена\s*[:\-]?)\s*[:\-]?\s*"
    r"([\d\s\u00a0]+(?:[.,]\d{1,2})?)\s*(?:руб|₽|RUB)?",
    re.IGNORECASE,
)
NMCK_RE = re.compile(
    r"(?:НМЦК|начальн\w*\s+макс\w*\s+цен\w*)\s*[:\-]?\s*"
    r"([\d\s\u00a0]+(?:[.,]\d{1,2})?)",
    re.IGNORECASE,
)
REESTR_RE = re.compile(r"(?:reestrNumber|regNumber)=([A-Za-z0-9\-]+)", re.IGNORECASE)
PURCHASE_RE = re.compile(
    r"(?:извещени\w*|закупк\w*|notice|purchaseNumber)\s*[:\-№#]?\s*([0-9]{11,25})",
    re.IGNORECASE,
)
INN_RE = re.compile(r"\bИНН\s*[:\-]?\s*(\d{10}|\d{12})\b", re.IGNORECASE)
OKPD_RE = re.compile(r"\b(\d{2}(?:\.\d{1,3}){1,4})\b")
DIGITS_RE = re.compile(r"[^\d.,]")

_HARD_TRANSPORT_MARKERS = (
    "connecterror",
    "connecttimeout",
    "readtimeout",
    "timeout",
    "sslerror",
    "proxyerror",
    "networkerror",
)


def _proxy_configured() -> bool:
    return bool(
        (settings.scrape_proxy_url or "").strip()
        or (settings.http_proxy or "").strip()
        or (settings.https_proxy or "").strip()
        or (settings.all_proxy or "").strip()
    )


def _geo_hint(base: str) -> str:
    if _proxy_configured():
        return f"{base}. Прокси отвечает, но ЕИС пуст/режет (geo/captcha)."
    return f"{base}. Нужен SCRAPE_PROXY_URL (RU ISP/residential)"


def _parse_money(text: str | None, pattern: re.Pattern[str] | None = None) -> float | None:
    if not text:
        return None
    raw = None
    if pattern:
        m = pattern.search(text.replace("\xa0", " "))
        raw = m.group(1) if m else None
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
        dt = date_parser.parse(value, dayfirst=True)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except (TypeError, ValueError, OverflowError):
        return None


def _external_id_from_url(url: str, fallback: str) -> str:
    match = REESTR_RE.search(url)
    if match:
        return match.group(1)
    path = urlparse(url).path.rstrip("/").split("/")[-1]
    return path or fallback[:40]


def _first_inn(text: str | None) -> str | None:
    if not text:
        return None
    m = INN_RE.search(text)
    return m.group(1) if m else None


def _extract_labeled(text: str, labels: tuple[str, ...]) -> str | None:
    low = text.lower()
    for label in labels:
        idx = low.find(label.lower())
        if idx < 0:
            continue
        chunk = text[idx + len(label) : idx + len(label) + 220]
        chunk = re.split(r"(?:\n|<br|Заказчик|Поставщик|Цена|ИНН|Регион|ОКПД)", chunk, maxsplit=1)[0]
        clean = BeautifulSoup(chunk, "lxml").get_text(" ", strip=True)
        clean = re.sub(r"^[\s:\-–—]+", "", clean).strip()
        if clean:
            return clean[:500]
    return None


class EisContractParser:
    """ЕИС реестр контрактов 44-ФЗ / договоров 223-ФЗ."""

    def __init__(self, law: str) -> None:
        if law not in {"44", "223"}:
            raise ValueError("law must be 44 or 223")
        self.law = law
        self.source = f"eis_contract_{law}"
        self.display_name = f"ЕИС контракты · {law}-ФЗ"
        self.last_fetch_note: str | None = None

    def _rss_url(self, page: int = 1, search_string: str | None = None) -> str:
        if self.law == "44":
            root = "https://zakupki.gov.ru/epz/contract/search/rss.html"
            law_flag = "fz44"
        else:
            root = "https://zakupki.gov.ru/epz/contractfz223/search/rss.html"
            law_flag = "fz223"
        params = {
            "morphology": "on",
            "search-filter": "Дате размещения",
            "pageNumber": str(page),
            "sortDirection": "false",
            "recordsPerPage": "_50",
            "sortBy": "UPDATE_DATE",
            law_flag: "on",
            "currencyIdGeneral": "-1",
        }
        if search_string:
            params["searchString"] = search_string
        return f"{root}?{urlencode(params)}"

    def _html_url(self, page: int = 1, search_string: str | None = None) -> str:
        params = parse_qs(urlparse(self._rss_url(page, search_string=search_string)).query)
        flat = {k: v[0] for k, v in params.items()}
        if self.law == "44":
            root = "https://zakupki.gov.ru/epz/contract/search/results.html"
        else:
            root = "https://zakupki.gov.ru/epz/contractfz223/search/results.html"
        return f"{root}?{urlencode(flat)}"

    def _page_budget(self) -> int:
        max_pages = max(1, int(getattr(settings, "contracts_max_pages", 5)))
        if _proxy_configured():
            return min(8, max_pages)
        return min(3, max_pages)

    async def fetch(self, search_string: str | None = None) -> list[ParsedContract]:
        headers = {
            "Accept": "application/rss+xml, application/xml, text/xml, */*;q=0.8",
            "Accept-Language": "ru-RU,ru;q=0.9,en;q=0.5",
        }
        items, hard = await self._from_rss(headers, search_string=search_string)
        if items:
            self.last_fetch_note = None
            return items
        if hard:
            if not self.last_fetch_note:
                self.last_fetch_note = _geo_hint(f"ЕИС контракты {self.law}-ФЗ: сеть/таймаут")
            return []
        html_items = await self._from_html(search_string=search_string)
        if html_items:
            self.last_fetch_note = None
            return html_items
        if not self.last_fetch_note:
            self.last_fetch_note = _geo_hint(f"ЕИС контракты {self.law}-ФЗ недоступны")
        return []

    async def _from_rss(
        self,
        headers: dict[str, str],
        search_string: str | None = None,
    ) -> tuple[list[ParsedContract], bool]:
        from app.services.http_client import cached_get

        items: list[ParsedContract] = []
        notes: list[str] = []
        hard_transport = False
        pages = self._page_budget()
        for page in range(1, pages + 1):
            url = self._rss_url(page, search_string=search_string)
            try:
                response = await cached_get(url, headers=headers)
            except httpx.HTTPError as exc:
                name = type(exc).__name__.lower()
                hard_transport = any(m in name for m in _HARD_TRANSPORT_MARKERS)
                notes.append(f"RSS {type(exc).__name__}")
                break
            if response.status_code != 200:
                notes.append(f"RSS HTTP {response.status_code}")
                if response.status_code in {403, 429, 451}:
                    notes.append("geo/captcha?")
                break
            low = response.text.lower()
            if "<item" not in low and "<entry" not in low:
                notes.append("RSS без item")
                break
            feed = feedparser.parse(response.text)
            page_items = self._parse_rss_feed(feed)
            if not page_items:
                break
            items.extend(page_items)
        if notes and not items:
            joined = "; ".join(notes[:4])
            self.last_fetch_note = _geo_hint(joined) if "geo" in joined.lower() or "captcha" in joined.lower() else joined
        return self._dedupe(items), hard_transport

    def _parse_rss_feed(self, feed) -> list[ParsedContract]:
        items: list[ParsedContract] = []
        for entry in feed.entries:
            link = getattr(entry, "link", "") or ""
            title = (getattr(entry, "title", None) or "").strip()
            if not title or not link:
                continue
            summary = getattr(entry, "summary", None) or getattr(entry, "description", None) or ""
            published = _parse_datetime(
                getattr(entry, "published", None) or getattr(entry, "updated", None)
            )
            clean = BeautifulSoup(summary, "lxml").get_text(" ", strip=True)
            supplier = _extract_labeled(clean, ("Поставщик", "Исполнитель", "Подрядчик"))
            customer = _extract_labeled(clean, ("Заказчик", "Организация"))
            purchase = None
            pm = PURCHASE_RE.search(clean) or PURCHASE_RE.search(title)
            if pm:
                purchase = pm.group(1)
            items.append(
                ParsedContract(
                    external_id=_external_id_from_url(link, title),
                    source=self.source,
                    law=f"{self.law}-ФЗ",
                    title=BeautifulSoup(title, "lxml").get_text(" ", strip=True),
                    url=link,
                    purchase_number=purchase,
                    customer=customer,
                    customer_inn=_first_inn(customer or "") or _first_inn(clean),
                    supplier_name=supplier,
                    supplier_inn=_first_inn(supplier or ""),
                    price=_parse_money(clean, PRICE_RE) or _parse_money(clean),
                    nmck=_parse_money(clean, NMCK_RE),
                    description=clean[:2500] or None,
                    status="Исполнение" if "исполнен" not in clean.lower() else "Исполнение завершено",
                    okpd2=(OKPD_RE.search(clean).group(1) if OKPD_RE.search(clean) else None),
                    signed_at=published,
                    published_at=published,
                )
            )
        return items

    async def _from_html(self, search_string: str | None = None) -> list[ParsedContract]:
        from app.services.http_client import cached_get

        headers = {
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "ru-RU,ru;q=0.9,en;q=0.5",
        }
        items: list[ParsedContract] = []
        notes: list[str] = []
        for page in range(1, self._page_budget() + 1):
            url = self._html_url(page, search_string=search_string)
            try:
                response = await cached_get(url, headers=headers)
            except httpx.HTTPError as exc:
                notes.append(type(exc).__name__)
                break
            if response.status_code != 200:
                notes.append(f"HTML HTTP {response.status_code}")
                break
            page_items = self._parse_html(response.text)
            if not page_items:
                if page == 1:
                    low = response.text.lower()
                    if "captcha" in low or "доступ ограничен" in low:
                        notes.append("geo/captcha")
                break
            items.extend(page_items)
        if notes and not items:
            joined = "; ".join(notes[:3])
            self.last_fetch_note = _geo_hint(joined) if "geo" in joined.lower() or "captcha" in joined.lower() else joined
        return self._dedupe(items)

    def _parse_html(self, html: str) -> list[ParsedContract]:
        soup = BeautifulSoup(html, "lxml")
        blocks = soup.select(
            ".search-registry-entry-block, .registry-entry, .card-common, "
            ".search-registry-docket, div[class*='registry-entry']"
        )
        if not blocks:
            # Fallback: any anchors to contract cards
            blocks = []
            for a in soup.select("a[href*='contractCard'], a[href*='contractfz223'], a[href*='reestrNumber=']"):
                parent = a.find_parent(["div", "article", "tr", "li"])
                if parent and parent not in blocks:
                    blocks.append(parent)

        items: list[ParsedContract] = []
        for block in blocks:
            link_el = block.select_one(
                "a[href*='reestrNumber='], a[href*='contractCard'], a[href*='contract-info']"
            )
            if not link_el or not link_el.get("href"):
                continue
            href = link_el["href"]
            if href.startswith("/"):
                href = "https://zakupki.gov.ru" + href
            title = link_el.get_text(" ", strip=True) or ""
            text = block.get_text(" ", strip=True)
            if not title:
                title = (text[:180] + "…") if len(text) > 180 else text
            if not title:
                continue
            supplier = _extract_labeled(text, ("Поставщик", "Исполнитель", "Подрядчик"))
            customer = _extract_labeled(text, ("Заказчик",))
            purchase = None
            pm = PURCHASE_RE.search(text)
            if pm:
                purchase = pm.group(1)
            price = _parse_money(text, PRICE_RE) or _parse_money(text)
            date_m = re.search(r"\d{2}\.\d{2}\.\d{4}", text)
            published = _parse_datetime(date_m.group(0) if date_m else None)
            items.append(
                ParsedContract(
                    external_id=_external_id_from_url(href, title),
                    source=self.source,
                    law=f"{self.law}-ФЗ",
                    title=title,
                    url=href,
                    purchase_number=purchase,
                    customer=customer,
                    customer_inn=_first_inn(customer or "") or _first_inn(text),
                    supplier_name=supplier,
                    supplier_inn=_first_inn(supplier or ""),
                    price=price,
                    nmck=_parse_money(text, NMCK_RE),
                    description=text[:2500] or None,
                    okpd2=(OKPD_RE.search(text).group(1) if OKPD_RE.search(text) else None),
                    status="Контракт",
                    published_at=published,
                    signed_at=published,
                )
            )
        return items

    @staticmethod
    def _dedupe(items: list[ParsedContract]) -> list[ParsedContract]:
        seen: set[str] = set()
        unique: list[ParsedContract] = []
        for item in items:
            if item.external_id in seen:
                continue
            seen.add(item.external_id)
            unique.append(item)
        return unique


def get_contract_parsers() -> list[EisContractParser]:
    return [EisContractParser("44"), EisContractParser("223")]
