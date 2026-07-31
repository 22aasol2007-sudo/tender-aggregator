from __future__ import annotations

from datetime import datetime, timedelta, timezone
from random import choice, randint, uniform

from sqlalchemy.orm import Session

from app.models import FilterPreset, Tender
from app.parsers.base import ParsedTender
from app.services.niche import TRANSPORT_EXCLUDE, TRANSPORT_PRESET_FILTERS, TRANSPORT_Q


SAMPLE_TITLES = [
    "Оказание услуг по перевозке грузов автомобильным транспортом",
    "Перевозка продуктов питания рефрижератором",
    "Транспортно-экспедиционные услуги по доставке грузов",
    "Услуги грузоперевозок изотермическим транспортом",
    "Перевозка скоропортящихся грузов с температурным режимом",
    "Автоперевозка товаров по маршруту заказчика",
    "Фрахт рефрижераторной фуры",
    "Логистические услуги и экспедирование грузов",
    "Перевозка замороженной продукции рефтранспортом",
    "Услуги по перевозке сборных грузов",
    "Контейнерные перевозки автомобильным транспортом",
    "Доставка грузов тентованным транспортом",
]

CUSTOMERS = [
    "ООО «Торговый дом Продукты»",
    "АО «Региональный распределительный центр»",
    "ГБУ «Комбинат школьного питания»",
    "ООО «ХолодЛогистик»",
    "МУП «Городской рынок»",
    "ООО «АгроПоставка»",
]

REGIONS = [
    "Москва",
    "Санкт-Петербург",
    "Московская область",
    "Республика Татарстан",
    "Свердловская область",
    "Краснодарский край",
    "Новосибирская область",
]

METHODS = [
    "Электронный аукцион",
    "Запрос котировок",
    "Открытый конкурс",
    "Закупка у единственного поставщика",
]

BUILTIN_PRESETS = [
    {
        "name": "Грузоперевозки + реф",
        "description": "Рефрижератор и общие грузоперевозки (расширенные ключевые слова, OR)",
        "filters": {
            **TRANSPORT_PRESET_FILTERS,
            "q": TRANSPORT_Q,
            "exclude": TRANSPORT_EXCLUDE,
        },
    },
    {
        "name": "Только рефрижератор",
        "description": "Температурный режим, холодная цепь, изотерм",
        "filters": {
            "q": "рефрижератор, рефтранспорт, хладотранспорт, изотерм, температурный режим, скоропортящ, холодовая цепь, холодная цепь, охлажденн, замороженн, рефрижераторн",
            "exclude": "программное обеспечение, серверное оборудование, канцеляр, офисная мебель",
            "match_any": True,
            "status_norm": "accepting",
            "hide_outdated": True,
            "hide_duplicates": True,
        },
    },
]


def build_demo_tenders(count: int = 24) -> list[ParsedTender]:
    now = datetime.now(timezone.utc)
    items: list[ParsedTender] = []
    for i in range(count):
        law = "44-ФЗ" if i % 3 else "223-ФЗ"
        source = "zakupki_44" if law == "44-ФЗ" else "zakupki_223"
        ext = f"DEMO{100000 + i}"
        title = choice(SAMPLE_TITLES)
        low = title.lower()
        if any(x in low for x in ("реф", "изотерм", "скоропорт", "заморож", "температур", "холод")):
            okpd = "49.41.1"
        else:
            okpd = "49.41"
        items.append(
            ParsedTender(
                external_id=ext,
                source=source,
                law=law,
                title=title,
                customer=choice(CUSTOMERS),
                region=choice(REGIONS),
                price=round(uniform(150_000, 45_000_000), 2),
                status="Подача заявок",
                method=choice(METHODS),
                okpd2=okpd,
                url=f"https://zakupki.gov.ru/epz/order/notice/view/common-info.html?regNumber={ext}",
                description="Демо-запись: используется, пока внешний источник недоступен.",
                documents=[{"name": "Извещение.pdf", "url": None}],
                lots=[{"name": title, "price": round(uniform(150_000, 5_000_000), 2), "okpd2": okpd}],
                published_at=now - timedelta(hours=randint(1, 120)),
                deadline_at=now + timedelta(days=randint(3, 21)),
            )
        )
    return items


def seed_if_empty(db: Session) -> int:
    if db.query(Tender).count() > 0:
        return 0
    from app.services.aggregator import upsert_tenders

    upserted, _skipped, _ids = upsert_tenders(db, build_demo_tenders())
    return upserted


def seed_presets(db: Session) -> None:
    wanted = {p["name"] for p in BUILTIN_PRESETS}
    obsolete = (
        db.query(FilterPreset)
        .filter(FilterPreset.is_builtin.is_(True), FilterPreset.name.notin_(wanted))
        .all()
    )
    for row in obsolete:
        db.delete(row)

    for preset in BUILTIN_PRESETS:
        existing = (
            db.query(FilterPreset)
            .filter(FilterPreset.name == preset["name"], FilterPreset.is_builtin.is_(True))
            .one_or_none()
        )
        if existing:
            existing.filters = preset["filters"]
            existing.description = preset["description"]
            existing.is_builtin = True
            existing.is_shared = True
        else:
            db.add(
                FilterPreset(
                    name=preset["name"],
                    description=preset["description"],
                    filters=preset["filters"],
                    is_builtin=True,
                    is_shared=True,
                )
            )
    db.commit()


def cleanup_polluted_tenders(db: Session) -> int:
    """Remove demo rows and junk parser artifacts (sort-link IDs, header titles)."""
    from sqlalchemy import or_

    junk_titles = ["Опубликовано", "Название", "Наименование", "Заказчик", "Цена", "Статус"]
    q = db.query(Tender).filter(
        or_(
            Tender.external_id.like("DEMO%"),
            Tender.external_id.like("order_by%"),
            Tender.title.in_(junk_titles),
        )
    )
    count = q.count()
    if count:
        q.delete(synchronize_session=False)
        db.commit()
    return count
