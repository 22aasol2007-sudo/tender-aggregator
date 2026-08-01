from __future__ import annotations

import hashlib
import json
from typing import Any
from urllib.parse import urljoin

import httpx
from bs4 import BeautifulSoup

from app.config import settings
from app.parsers.base import ParsedTender
from app.parsers.commercial import (
    CommercialHtmlParser,
    _extract_external_id,
    _is_junk_row,
    _parse_dt,
    _parse_price,
)


class EtpGpbParser(CommercialHtmlParser):
    def __init__(self) -> None:
        self.source = "etp_gpb"
        self.display_name = "ЭТП ГПБ"
        self.base_url = "https://etpgpb.ru"
        self.public_listing = False
        self.unavailable_reason = "ЭТП ГПБ: лента процедур в Nuxt SPA, публичный HTML без списка"
        self.search_urls = ["https://etpgpb.ru/", "https://gos.etpgpb.ru/"]


class TekTorgParser(CommercialHtmlParser):
    def __init__(self) -> None:
        self.source = "tektorg"
        self.display_name = "ТЕК-Торг"
        self.base_url = "https://www.tektorg.ru"
        self.public_listing = True
        self.unavailable_reason = None
        self.search_urls = [
            "https://www.tektorg.ru/223-fz/procedures",
            "https://www.tektorg.ru/44-fz/procedures",
        ]

    async def fetch(self) -> list[ParsedTender]:
        items = await self._from_next_data()
        if items:
            return items
        return await self._fetch_html()

    async def _from_next_data(self) -> list[ParsedTender]:
        import json
        import re

        from app.services.http_client import cached_get

        headers = {
            "Accept": "text/html,application/xhtml+xml",
            "Accept-Language": "ru-RU,ru;q=0.9",
        }
        for url in self.search_urls:
            try:
                resp = await cached_get(url, headers=headers)
            except httpx.HTTPError as exc:
                self.last_fetch_note = f"{type(exc).__name__}"
                continue
            if resp.status_code != 200:
                continue
            body = resp.text
            if "защитой от ботов" in body.lower() or "ddos" in body.lower() and "прерван" in body.lower():
                self.last_fetch_note = "ТЕК-Торг: антибот/DDoS защита"
                continue
            m = re.search(
                r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>',
                body,
                re.S,
            )
            if not m:
                # Fallback: harvest procedure links from HTML when Next blob missing
                from bs4 import BeautifulSoup

                soup = BeautifulSoup(body, "lxml")
                html_items = self._parse_links(soup, url)
                if html_items:
                    self.last_fetch_note = None
                    return html_items
                continue
            try:
                data = json.loads(m.group(1))
            except json.JSONDecodeError:
                continue
            rows = (
                data.get("props", {})
                .get("pageProps", {})
                .get("initialReduxState", {})
                .get("listingProcedures", {})
                .get("data")
                or []
            )
            items: list[ParsedTender] = []
            section = "223-fz" if "223" in url else "44-fz"
            for row in rows[:40]:
                if not isinstance(row, dict):
                    continue
                title = str(row.get("title") or "").strip()
                pid = row.get("id") or row.get("remoteId") or row.get("registryNumber")
                if not title or not pid:
                    continue
                href = f"{self.base_url}/{section}/procedures/{pid}"
                dates = row.get("dates") or {}
                items.append(
                    ParsedTender(
                        external_id=str(pid)[:64],
                        source=self.source,
                        title=title[:500],
                        url=href,
                        customer=row.get("organizerName"),
                        price=_parse_price(str(row.get("sumPrice") or "")),
                        status=str(row.get("statusName") or "Подача заявок"),
                        method=row.get("typeName"),
                        law="223-ФЗ" if section.startswith("223") else "44-ФЗ",
                        description=str(row.get("registryNumber") or "")[:500] or None,
                        published_at=_parse_dt(str(dates.get("datePublished") or "")),
                        deadline_at=_parse_dt(str(dates.get("dateEndRegistration") or "")),
                    )
                )
            if items:
                self.last_fetch_note = None
                return items
        return []


class FabrikantParser(CommercialHtmlParser):
    def __init__(self) -> None:
        self.source = "fabrikant"
        self.display_name = "Фабрикант"
        self.base_url = "https://www.fabrikant.ru"
        # Single SSR search page (second URL was burning the 90s source budget on Railway)
        self.search_urls = [
            "https://www.fabrikant.ru/trades/procedure/search/",
        ]

    def _parse_links(self, soup: BeautifulSoup, page_url: str) -> list[ParsedTender]:
        """Prefer /v2/trades/procedure/view/ anchors from Next.js SSR HTML."""
        items: list[ParsedTender] = []
        for idx, link in enumerate(soup.select("a[href*='/v2/trades/procedure/view/'], a[href*='/44/procedure/']")):
            href = link.get("href") or ""
            title = link.get_text(" ", strip=True)
            if not title or len(title) < 12:
                continue
            if href.startswith("/"):
                href = urljoin(self.base_url, href)
            elif not href.startswith("http"):
                continue
            if _is_junk_row(href, title):
                continue
            ext = _extract_external_id(href, self.source, idx)
            if not ext:
                continue
            parent_text = ""
            parent = link.find_parent(["article", "div", "li", "tr"])
            if parent is not None:
                parent_text = parent.get_text(" ", strip=True)[:1500]
            items.append(
                ParsedTender(
                    external_id=ext[:64],
                    source=self.source,
                    title=title[:500],
                    url=href.split("#")[0],
                    price=_parse_price(parent_text),
                    status="Подача заявок",
                    description=parent_text or None,
                    law="223-ФЗ",
                )
            )
        return self._dedupe(items) if items else super()._parse_links(soup, page_url)


class OtcParser(CommercialHtmlParser):
    def __init__(self) -> None:
        self.source = "otc"
        self.display_name = "OTC-tender"
        self.base_url = "https://etp.otc.ru"
        self.public_listing = True
        self.unavailable_reason = None
        self.search_urls = [
            "https://etp.otc.ru/tenders-search",
            "https://etp.otc.ru/tenders/223-fz",
            "https://www.otc.ru/tenders-search/223-fz",
        ]


class AgzrtParser(CommercialHtmlParser):
    def __init__(self) -> None:
        self.source = "agzrt"
        self.display_name = "АГЗ РТ"
        self.base_url = "https://agzrt.ru"
        self.public_listing = False
        self.unavailable_reason = "АГЗ РТ: лендинг; торги на zakazrf.ru / 223etp без открытого HTML-списка"
        self.search_urls = [
            "https://agzrt.ru/",
            "https://223etp.zakazrf.ru/",
            "https://zakazrf.ru/",
        ]


class RostenderParser(CommercialHtmlParser):
    def __init__(self) -> None:
        self.source = "rostender"
        self.display_name = "Rostender"
        self.base_url = "https://rostender.info"
        self.search_urls = [
            "https://rostender.info/extsearch",
            "https://rostender.info/",
        ]


class TorgiGovParser(CommercialHtmlParser):
    """torgi.gov.ru public lotcards JSON API (works from abroad without HTML SPA)."""

    def __init__(self) -> None:
        self.source = "torgi_gov"
        self.display_name = "torgi.gov.ru"
        self.base_url = "https://torgi.gov.ru"
        self.public_listing = True
        self.unavailable_reason = None
        self.search_urls = [
            "https://torgi.gov.ru/new/api/public/lotcards/search?page=0&size=20&lotStatus=APPLICATIONS_SUBMISSION",
            "https://torgi.gov.ru/new/api/public/lotcards/search?page=0&size=20",
        ]

    async def fetch(self) -> list[ParsedTender]:
        from app.services.http_client import cached_get

        headers = {"Accept": "application/json", "Accept-Language": "ru-RU,ru;q=0.9"}
        notes: list[str] = []
        for url in self.search_urls:
            try:
                resp = await cached_get(url, headers=headers, ttl=120.0)
            except httpx.HTTPError as exc:
                notes.append(type(exc).__name__)
                continue
            if resp.status_code != 200:
                notes.append(f"HTTP {resp.status_code}")
                continue
            try:
                payload = resp.json()
            except json.JSONDecodeError:
                notes.append("bad json")
                continue
            rows = payload.get("content") if isinstance(payload, dict) else None
            if not isinstance(rows, list):
                notes.append("no content")
                continue
            items: list[ParsedTender] = []
            for row in rows[:40]:
                if not isinstance(row, dict):
                    continue
                notice = str(row.get("noticeNumber") or row.get("id") or "").strip()
                title = str(
                    row.get("lotName")
                    or row.get("lotDescription")
                    or row.get("noticeName")
                    or (row.get("biddType") or {}).get("name")
                    or ""
                ).strip()
                # Enrich short lot names with type / cadastral / address
                chars = row.get("characteristics") or []
                extras: list[str] = []
                for ch in chars:
                    if not isinstance(ch, dict):
                        continue
                    code = str(ch.get("code") or "")
                    val = ch.get("characteristicValue")
                    if code in {"CadastralNumber", "EstateAddress", "SubjectRF"} and val:
                        extras.append(str(val)[:80])
                bidd = (row.get("biddType") or {}).get("name")
                if bidd and bidd.lower() not in title.lower():
                    extras.insert(0, str(bidd))
                if extras and len(title) < 40:
                    title = f"{title} — {', '.join(extras[:3])}"
                if not notice or len(title) < 3:
                    continue
                href = f"{self.base_url}/new/public/lots/lot/{notice}_{row.get('lotNumber') or 1}"
                if row.get("id"):
                    href = f"{self.base_url}/new/public/lots/lot/{row['id']}"
                price_raw = row.get("priceMin") or row.get("priceMax") or row.get("price")
                items.append(
                    ParsedTender(
                        external_id=str(row.get("id") or notice)[:64],
                        source=self.source,
                        title=title[:500],
                        url=href,
                        region=str((row.get("subjectRF") or "") or "")[:120] or None,
                        price=_parse_price(str(price_raw or "")),
                        status=str(row.get("lotStatus") or "Подача заявок"),
                        method=(row.get("biddType") or {}).get("name"),
                        law=None,
                        description=str(row.get("biddForm", {}).get("name") or "")[:500] or None,
                        published_at=_parse_dt(str(row.get("firstVersionCreationDate") or row.get("createDate") or "")),
                        deadline_at=_parse_dt(str(row.get("biddEndTime") or row.get("applicationEndDate") or "")),
                    )
                )
            if items:
                self.last_fetch_note = None
                return items
        self.last_fetch_note = "; ".join(notes[:3]) if notes else "torgi.gov.ru API пуст"
        return []


class FedresursParser(CommercialHtmlParser):
    def __init__(self) -> None:
        self.source = "fedresurs"
        self.display_name = "Федресурс"
        self.base_url = "https://fedresurs.ru"
        self.public_listing = False
        self.unavailable_reason = "Федресурс: Angular SPA; backend API закрыт (403/401)"
        self.search_urls = [
            "https://fedresurs.ru/bankruptmessages",
            "https://fedresurs.ru/",
        ]


class KartotekaParser(CommercialHtmlParser):
    def __init__(self) -> None:
        self.source = "kartoteka"
        self.display_name = "Картотека"
        self.base_url = "https://www.kartoteka.ru"
        self.public_listing = False
        self.unavailable_reason = "Картотека: публичный HTML без устойчивых карточек торгов (нужен доступ/API)"
        self.search_urls = ["https://www.kartoteka.ru/bankruptcy/", "https://www.kartoteka.ru/"]


class ApiBackedParser(CommercialHtmlParser):
    """Optional JSON API with token from settings. Without credentials → needs_api."""

    api_url: str | None = None
    api_token: str | None = None
    requires_api: bool = True

    @property
    def api_ready(self) -> bool:
        return bool(self.api_url and self.api_token)

    async def fetch(self) -> list[ParsedTender]:
        if self.api_ready:
            items = await self._from_api()
            if items:
                return items
            self.last_fetch_note = "API не вернул данные"
            return []
        self.last_fetch_note = self.unavailable_reason or f"{self.display_name}: нужен API-ключ"
        return []

    async def _from_api(self) -> list[ParsedTender]:
        from app.services.http_client import cached_get

        headers = {
            "Accept": "application/json",
            "Authorization": f"Bearer {self.api_token}",
        }
        try:
            resp = await cached_get(self.api_url or "", headers=headers, ttl=60.0)
            if resp.status_code != 200:
                return []
            payload: Any
            try:
                payload = resp.json()
            except json.JSONDecodeError:
                return []
        except httpx.HTTPError:
            return []

        rows: list[Any]
        if isinstance(payload, list):
            rows = payload
        elif isinstance(payload, dict):
            rows = payload.get("items") or payload.get("data") or payload.get("results") or []
        else:
            rows = []

        items: list[ParsedTender] = []
        for idx, row in enumerate(rows[:40]):
            if not isinstance(row, dict):
                continue
            title = str(row.get("title") or row.get("name") or row.get("subject") or "").strip()
            url = str(row.get("url") or row.get("link") or self.base_url)
            if not title:
                continue
            ext = str(row.get("id") or row.get("number") or f"{self.source}-{idx}")[:64]
            items.append(
                ParsedTender(
                    external_id=ext,
                    source=self.source,
                    title=title[:500],
                    url=url,
                    customer=row.get("customer") or row.get("organizer"),
                    region=row.get("region"),
                    price=_parse_price(str(row.get("price") or row.get("nmck") or "")),
                    status=str(row.get("status") or "Подача заявок"),
                    method=row.get("method"),
                    okpd2=row.get("okpd2") or row.get("okpd"),
                    law=row.get("law") or "223-ФЗ",
                    description=str(row.get("description") or "")[:1500] or None,
                    published_at=_parse_dt(str(row.get("published_at") or row.get("date") or "")),
                    deadline_at=_parse_dt(str(row.get("deadline_at") or row.get("end_date") or "")),
                )
            )
        return items


class ContourParser(ApiBackedParser):
    def __init__(self) -> None:
        self.source = "contour"
        self.display_name = "Контур.Закупки"
        self.base_url = "https://zakupki.kontur.ru"
        self.search_urls = ["https://zakupki.kontur.ru/"]
        self.api_url = settings.contour_api_url
        self.api_token = settings.contour_api_token
        self.public_listing = False
        self.unavailable_reason = "Контур.Закупки: нужен CONTOUR_API_URL + CONTOUR_API_TOKEN"


class TenderplanParser(ApiBackedParser):
    def __init__(self) -> None:
        self.source = "tenderplan"
        self.display_name = "Tenderplan"
        self.base_url = "https://tenderplan.ru"
        self.search_urls = ["https://tenderplan.ru/"]
        self.api_url = settings.tenderplan_api_url
        self.api_token = settings.tenderplan_api_token
        self.public_listing = False
        self.unavailable_reason = "Tenderplan: нужен TENDERPLAN_API_URL + TENDERPLAN_API_TOKEN"


class TenderlandParser(ApiBackedParser):
    def __init__(self) -> None:
        self.source = "tenderland"
        self.display_name = "Tenderland"
        self.base_url = "https://tenderland.ru"
        self.search_urls = ["https://tenderland.ru/"]
        self.api_url = settings.tenderland_api_url
        self.api_token = settings.tenderland_api_token
        self.public_listing = False
        self.unavailable_reason = "Tenderland: нужен TENDERLAND_API_URL + TENDERLAND_API_TOKEN"


class SynapseParser(ApiBackedParser):
    def __init__(self) -> None:
        self.source = "synapse"
        self.display_name = "Synapse"
        self.base_url = "https://synapsenet.ru"
        self.search_urls = ["https://synapsenet.ru/"]
        self.api_url = settings.synapse_api_url
        self.api_token = settings.synapse_api_token
        self.public_listing = False
        self.unavailable_reason = "Synapse: нужен SYNAPSE_API_URL + SYNAPSE_API_TOKEN"


class EisRegistryParser:
    """РНП / банк гарантий ЕИС — смежные реестры, не классические тендеры."""

    source: str
    display_name: str
    search_urls: list[str]
    base_url: str = "https://zakupki.gov.ru"
    requires_api: bool = False
    public_listing: bool = True
    unavailable_reason: str | None = None
    last_fetch_note: str | None = None

    @property
    def api_ready(self) -> bool:
        return False

    async def fetch(self) -> list[ParsedTender]:
        from app.services.http_client import cached_get

        headers = {
            "Accept": "text/html,application/xhtml+xml",
        }
        items: list[ParsedTender] = []
        notes: list[str] = []
        for url in self.search_urls:
            try:
                resp = await cached_get(url, headers=headers)
            except httpx.HTTPError as exc:
                notes.append(f"{type(exc).__name__}")
                continue
            if resp.status_code != 200:
                notes.append(f"HTTP {resp.status_code}")
                continue
            soup = BeautifulSoup(resp.text, "lxml")
            for idx, block in enumerate(soup.select(".search-registry-entry-block, .registry-entry, tr, article")[:30]):
                link = block.select_one("a[href]")
                title = (link.get_text(" ", strip=True) if link else block.get_text(" ", strip=True))[:500]
                if not title or len(title) < 10:
                    continue
                href = link.get("href") if link else url
                if href and href.startswith("/"):
                    href = self.base_url + href
                items.append(
                    ParsedTender(
                        external_id=f"{self.source}-{hashlib.sha1((title or href or str(idx)).encode()).hexdigest()[:12]}",
                        source=self.source,
                        title=title,
                        url=href or url,
                        status="Реестр",
                        description=block.get_text(" ", strip=True)[:1500],
                    )
                )
            if items:
                break
        self.last_fetch_note = "; ".join(notes[:3]) if notes and not items else None
        return items


class RnpParser(EisRegistryParser):
    def __init__(self) -> None:
        self.source = "rnp"
        self.display_name = "РНП (ЕИС)"
        self.search_urls = [
            "https://zakupki.gov.ru/epz/dishonestsupplier/search/results.html",
            "https://zakupki.gov.ru/epz/dishonestsupplier/quicksearch/search.html",
        ]


class BankGuaranteesParser(EisRegistryParser):
    def __init__(self) -> None:
        self.source = "bank_guarantees"
        self.display_name = "Банк гарантий (ЕИС)"
        self.search_urls = [
            "https://zakupki.gov.ru/epz/bankguarantee/search/results.html",
            "https://zakupki.gov.ru/",
        ]


def get_extra_parsers() -> list:
    return [
        EtpGpbParser(),
        TekTorgParser(),
        FabrikantParser(),
        OtcParser(),
        AgzrtParser(),
        ContourParser(),
        TenderplanParser(),
        TenderlandParser(),
        SynapseParser(),
        RostenderParser(),
        TorgiGovParser(),
        RnpParser(),
        BankGuaranteesParser(),
        FedresursParser(),
        KartotekaParser(),
    ]
