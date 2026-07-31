from __future__ import annotations

from datetime import datetime, timedelta, timezone
from random import choice, randint, uniform

from sqlalchemy.orm import Session

from app.models import FilterPreset, Tender
from app.parsers.base import ParsedTender


SAMPLE_TITLES = [
    "Поставка серверного оборудования и СХД",
    "Оказание услуг по сопровождению ИС",
    "Закупка канцелярских товаров",
    "Поставка лекарственных препаратов",
    "Выполнение работ по ремонту кровли",
    "Оказание охранных услуг",
    "Поставка легковых автомобилей",
    "Услуги связи и передачи данных",
    "Поставка продуктов питания",
    "Разработка программного обеспечения",
    "Техническое обслуживание зданий",
    "Поставка офисной мебели",
]

CUSTOMERS = [
    "ГБУ «Городская поликлиника №12»",
    "Министерство цифрового развития региона",
    "МУП «Водоканал»",
    "ФГБОУ ВО «Технический университет»",
    "Администрация городского округа",
    "ГУП «Дорожное хозяйство»",
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
        "name": "ИТ",
        "description": "ПО, серверы, связь и цифровые услуги",
        "filters": {
            "q": "программ сервер ИТ информацион",
            "okpd2": "62",
            "status_norm": "accepting",
            "hide_outdated": True,
            "hide_duplicates": True,
        },
    },
    {
        "name": "Строительство",
        "description": "Строительные и ремонтные работы",
        "filters": {
            "q": "строитель ремонт кровл дорог",
            "okpd2": "41",
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
        okpd = "62.01" if "программ" in title.lower() or "сервер" in title.lower() or "ИС" in title else "41.20"
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
