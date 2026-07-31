from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from random import choice, randint, uniform
from urllib.parse import urljoin

import certifi
import httpx
from bs4 import BeautifulSoup
from dateutil import parser as date_parser

from app.config import settings
from app.parsers.base import ParsedTender


def _ssl_verify() -> bool | str:
    if not settings.http_verify_ssl:
        return False
    return certifi.where()


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        dt = date_parser.parse(value, dayfirst=True)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except (TypeError, ValueError, OverflowError):
        return None


def _parse_price(text: str | None) -> float | None:
    if not text:
        return None
    cleaned = re.sub(r"[^\d.,]", "", text.replace(" ", "").replace("\xa0", "")).replace(",", ".")
    try:
        value = float(cleaned)
    except ValueError:
        return None
    return value if value > 0 else None


SAMPLE_BY_SOURCE = {
    "rts": {
        "host": "https://www.rts-tender.ru",
        "titles": [
            "Поставка компьютерной техники (РТС)",
            "Услуги по сопровождению ПО",
            "Закупка расходных материалов",
        ],
    },
    "roseltorg": {
        "host": "https://www.roseltorg.ru",
        "titles": [
            "Электронный аукцион: поставка оборудования",
            "Оказание транспортных услуг",
            "Поставка мебели для учреждений",
        ],
    },
    "sber_ast": {
        "host": "https://www.sberbank-ast.ru",
        "titles": [
            "Закупка продуктов питания",
            "Ремонт помещений",
            "Поставка медицинских изделий",
        ],
    },
    "b2b_center": {
        "host": "https://www.b2b-center.ru",
        "titles": [
            "Коммерческая закупка металлопроката",
            "Поставка ГСМ",
            "Услуги клининга",
        ],
    },
    "etp_gpb": {
        "host": "https://etpgpb.ru",
        "titles": [
            "Закупка оборудования для инфраструктуры",
            "Оказание ИТ-услуг (ЭТП ГПБ)",
            "Поставка спецтехники",
        ],
    },
    "tektorg": {
        "host": "https://www.tektorg.ru",
        "titles": [
            "Закупка ТМЦ для ТЭК",
            "Подрядные работы на объекте",
            "Поставка трубопроводной арматуры",
        ],
    },
    "fabrikant": {
        "host": "https://www.fabrikant.ru",
        "titles": [
            "Коммерческая процедура: поставка товаров",
            "Запрос предложений на услуги",
            "Закупка канцтоваров и техники",
        ],
    },
    "otc": {
        "host": "https://www.otc.ru",
        "titles": [
            "Закупка по 223-ФЗ (OTC)",
            "Электронный аукцион OTC-tender",
            "Поставка хозяйственных товаров",
        ],
    },
    "agzrt": {
        "host": "https://agzrt.ru",
        "titles": [
            "Закупка для учреждений РТ",
            "Электронный аукцион АГЗ РТ",
            "Поставка продуктов питания (Татарстан)",
        ],
    },
    "contour": {
        "host": "https://zakupki.kontur.ru",
        "titles": [
            "Мониторинг закупки (Контур.Закупки)",
            "Подходящая процедура по профилю",
            "Новое извещение из Контура",
        ],
    },
    "tenderplan": {
        "host": "https://tenderplan.ru",
        "titles": [
            "Тендер из Tenderplan",
            "Закупка ПО и оборудования",
            "Строительные работы (мониторинг)",
        ],
    },
    "tenderland": {
        "host": "https://tenderland.ru",
        "titles": [
            "Процедура Tenderland",
            "Поставка материалов",
            "Услуги обслуживания",
        ],
    },
    "synapse": {
        "host": "https://synapsenet.ru",
        "titles": [
            "Закупка Synapse",
            "Коммерческий тендер",
            "Госзакупка из агрегатора",
        ],
    },
    "rostender": {
        "host": "https://rostender.info",
        "titles": [
            "Тендер Rostender",
            "Извещение 44-ФЗ (агрегатор)",
            "Закупка услуг связи",
        ],
    },
    "torgi_gov": {
        "host": "https://torgi.gov.ru",
        "titles": [
            "Аренда государственного имущества",
            "Продажа земельного участка",
            "Торги по имуществу РФ",
        ],
    },
    "rnp": {
        "host": "https://zakupki.gov.ru",
        "titles": [
            "Запись РНП: проверка контрагента",
            "Включение в реестр недобросовестных поставщиков",
            "Сведения РНП по поставщику",
        ],
    },
    "bank_guarantees": {
        "host": "https://zakupki.gov.ru",
        "titles": [
            "Независимая гарантия в реестре ЕИС",
            "Банковская гарантия по контракту",
            "Сведения о гарантии поставщика",
        ],
    },
    "fedresurs": {
        "host": "https://fedresurs.ru",
        "titles": [
            "Торги Федресурс: имущество должника",
            "Аукцион по банкротству",
            "Продажа активов на Федресурсе",
        ],
    },
    "kartoteka": {
        "host": "https://www.kartoteka.ru",
        "titles": [
            "Торги / банкротство (Картотека)",
            "Процедура реализации имущества",
            "Сведения о торгах должника",
        ],
    },
}

REGIONS = ["Москва", "Санкт-Петербург", "Московская область", "Свердловская область", "Республика Татарстан"]
CUSTOMERS = [
    "АО «Промышленная компания»",
    "ООО «Снабжение»",
    "ПАО «Региональные сети»",
    "ГУП «Сервис»",
]
METHODS = ["Электронный аукцион", "Запрос предложений", "Конкурс", "Закупка у единственного поставщика"]


def _demo_for(source: str, count: int = 8) -> list[ParsedTender]:
    meta = SAMPLE_BY_SOURCE[source]
    now = datetime.now(timezone.utc)
    items: list[ParsedTender] = []
    for i in range(count):
        ext = f"{source.upper().replace('_', '')}{1000 + i}"
        title = choice(meta["titles"])
        if source in {"rnp", "bank_guarantees"}:
            law = "44-ФЗ"
        elif source in {"torgi_gov", "fedresurs", "kartoteka", "b2b_center"}:
            law = None
        else:
            law = "223-ФЗ"
        items.append(
            ParsedTender(
                external_id=ext,
                source=source,
                law=law,
                title=title,
                customer=choice(CUSTOMERS),
                region=choice(REGIONS) if source != "rnp" else "Россия",
                price=None if source in {"rnp", "bank_guarantees"} else round(uniform(200_000, 20_000_000), 2),
                status="Подача заявок" if source not in {"rnp", "bank_guarantees"} else "Размещено",
                method=choice(METHODS) if source not in {"rnp", "bank_guarantees"} else "Реестровая запись",
                okpd2=None if source in {"rnp", "bank_guarantees"} else choice(["62.01", "41.20", "46.51", "49.41", "10.85"]),
                url=f"{meta['host']}/tender/{ext}",
                description=f"Запись с площадки {source}. Демо/fallback при недоступности HTML/API.",
                published_at=now - timedelta(hours=randint(1, 72)),
                deadline_at=None if source in {"rnp", "bank_guarantees"} else now + timedelta(days=randint(2, 18)),
            )
        )
    return items


class CommercialHtmlParser:
    """Базовый адаптер коммерческих ЭТП: пробует публичный HTML, иначе demo."""

    source: str
    display_name: str
    search_urls: list[str]
    base_url: str

    def __init__(self) -> None:
        raise NotImplementedError

    async def fetch(self) -> list[ParsedTender]:
        from app.services.http_client import cached_get

        headers = {
            "Accept": "text/html,application/xhtml+xml",
        }
        items: list[ParsedTender] = []
        for url in self.search_urls:
            try:
                resp = await cached_get(url, headers=headers)
            except httpx.HTTPError:
                continue
            if resp.status_code != 200:
                continue
            soup = BeautifulSoup(resp.text, "lxml")
            items.extend(self._parse_soup(soup, url))
            if items:
                break
        return items or _demo_for(self.source)


    def _parse_soup(self, soup: BeautifulSoup, page_url: str) -> list[ParsedTender]:
        items: list[ParsedTender] = []
        cards = soup.select("article, .tender, .procedure, .search-result, .lot, tr")[:40]
        for idx, card in enumerate(cards):
            link = card.select_one("a[href]")
            if not link:
                continue
            href = link.get("href") or ""
            title = link.get_text(" ", strip=True)
            if not title or len(title) < 8:
                continue
            if href.startswith("/"):
                href = urljoin(self.base_url, href)
            elif not href.startswith("http"):
                continue
            text = card.get_text(" ", strip=True)
            price = _parse_price(text)
            published = None
            for m in re.finditer(r"\d{2}[./]\d{2}[./]\d{2,4}", text):
                published = _parse_dt(m.group(0))
                if published:
                    break
            ext = re.sub(r"\W+", "", href[-24:]) or f"{self.source}-{idx}"
            items.append(
                ParsedTender(
                    external_id=ext[:64],
                    source=self.source,
                    title=title[:500],
                    url=href,
                    price=price,
                    status="Подача заявок",
                    description=text[:1500],
                    published_at=published,
                    law="223-ФЗ" if self.source != "b2b_center" else None,
                )
            )
        # de-dupe by external_id
        seen: set[str] = set()
        unique: list[ParsedTender] = []
        for item in items:
            if item.external_id in seen:
                continue
            seen.add(item.external_id)
            unique.append(item)
        return unique[:30]


class RtsParser(CommercialHtmlParser):
    def __init__(self) -> None:
        self.source = "rts"
        self.display_name = "РТС-тендер"
        self.base_url = "https://www.rts-tender.ru"
        self.search_urls = [
            "https://www.rts-tender.ru/search",
            "https://www.rts-tender.ru/",
        ]


class RoseltorgParser(CommercialHtmlParser):
    def __init__(self) -> None:
        self.source = "roseltorg"
        self.display_name = "Росэлторг"
        self.base_url = "https://www.roseltorg.ru"
        self.search_urls = [
            "https://www.roseltorg.ru/procedures",
            "https://www.roseltorg.ru/",
        ]


class SberAstParser(CommercialHtmlParser):
    def __init__(self) -> None:
        self.source = "sber_ast"
        self.display_name = "Сбербанк-АСТ"
        self.base_url = "https://www.sberbank-ast.ru"
        self.search_urls = [
            "https://www.sberbank-ast.ru/purchaseList.html",
            "https://www.sberbank-ast.ru/",
        ]


class B2BCenterParser(CommercialHtmlParser):
    def __init__(self) -> None:
        self.source = "b2b_center"
        self.display_name = "B2B-Center"
        self.base_url = "https://www.b2b-center.ru"
        self.search_urls = [
            "https://www.b2b-center.ru/market/",
            "https://www.b2b-center.ru/",
        ]
