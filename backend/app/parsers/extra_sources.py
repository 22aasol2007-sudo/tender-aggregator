from __future__ import annotations

import hashlib
import json
from typing import Any

import httpx
from bs4 import BeautifulSoup

from app.config import settings
from app.parsers.base import ParsedTender
from app.parsers.commercial import (
    CommercialHtmlParser,
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
        self.public_listing = False
        self.unavailable_reason = "ТЕК-Торг: Next.js SPA — список процедур не отдаётся в HTML"
        self.search_urls = [
            "https://www.tektorg.ru/223-fz/procedures",
            "https://www.tektorg.ru/44-fz/procedures",
            "https://www.tektorg.ru/procedures",
        ]


class FabrikantParser(CommercialHtmlParser):
    def __init__(self) -> None:
        self.source = "fabrikant"
        self.display_name = "Фабрикант"
        self.base_url = "https://www.fabrikant.ru"
        self.search_urls = [
            "https://fabrikant.ru/procedure/search/purchases",
            "https://www.fabrikant.ru/trades/procedure/search/",
        ]


class OtcParser(CommercialHtmlParser):
    def __init__(self) -> None:
        self.source = "otc"
        self.display_name = "OTC-tender"
        self.base_url = "https://www.otc.ru"
        self.public_listing = False
        self.unavailable_reason = "OTC-tender: публичный поиск — SPA/логин (etp.otc.ru), HTML без процедур"
        self.search_urls = [
            "https://www.otc.ru/tenders-search/223-fz",
            "https://tender.otc.ru/",
            "https://www.otc.ru/",
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
    def __init__(self) -> None:
        self.source = "torgi_gov"
        self.display_name = "torgi.gov.ru"
        self.base_url = "https://torgi.gov.ru"
        self.public_listing = False
        self.unavailable_reason = "torgi.gov.ru: SPA + API без стабильного публичного HTML"
        self.search_urls = [
            "https://torgi.gov.ru/new/public/lots/reg",
            "https://torgi.gov.ru/",
        ]


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
