"""Seed curated gofra suppliers for cosmetics_moscow_gofra niche."""

from __future__ import annotations

import re

from sqlalchemy.orm import Session

from app.models import NicheSupplier
from app.services.niches.gofra_cosmetics import NICHE_ID

# Public / well-known corrugated packaging players serving Moscow & nearby.
# Contacts are indicative; shortlist will also enrich from book / web research.
GOFRA_MOSCOW_SEED: list[dict] = [
    {
        "name": "ГОТЭК",
        "inn": "4632008860",
        "role": "manufacturer",
        "city": "Москва",
        "region": "Москва",
        "website": "https://www.gotek.ru",
        "tags": ["gofra", "гофрокартон", "производитель"],
        "trust_seed": 0.9,
        "notes": "Крупный производитель гофроупаковки, поставки по РФ",
    },
    {
        "name": "Архбум",
        "inn": "2901061727",
        "role": "manufacturer",
        "city": "Москва",
        "region": "Москва",
        "website": "https://www.arhbum.ru",
        "tags": ["gofra", "гофрокартон", "производитель"],
        "trust_seed": 0.88,
        "notes": "Производитель гофрокартона и упаковки",
    },
    {
        "name": "Каменская БКФ",
        "role": "manufacturer",
        "city": "Москва",
        "region": "Московская область",
        "website": "https://www.kbkf.ru",
        "tags": ["gofra", "гофрокороб", "производитель"],
        "trust_seed": 0.85,
    },
    {
        "name": "Национальная упаковочная компания",
        "role": "manufacturer",
        "city": "Москва",
        "region": "Москва",
        "website": "https://www.nupack.ru",
        "tags": ["gofra", "упаковка", "производитель"],
        "trust_seed": 0.82,
    },
    {
        "name": "Ярославский картонно-полиграфический комбинат",
        "role": "manufacturer",
        "city": "Москва",
        "region": "Ярославская область",
        "website": "https://www.yarcpk.ru",
        "tags": ["gofra", "картон", "производитель"],
        "trust_seed": 0.8,
    },
    {
        "name": "Смерфит Каппа Россия",
        "role": "manufacturer",
        "city": "Москва",
        "region": "Москва",
        "website": "https://www.smurfitkappa.com/ru",
        "tags": ["gofra", "гофроупаковка", "производитель"],
        "trust_seed": 0.88,
    },
    {
        "name": "Stora Enso Packaging",
        "role": "manufacturer",
        "city": "Москва",
        "region": "Москва",
        "website": "https://www.storaenso.com",
        "tags": ["gofra", "упаковка", "производитель"],
        "trust_seed": 0.86,
    },
    {
        "name": "ПЦБК",
        "role": "manufacturer",
        "city": "Москва",
        "region": "Пермский край",
        "website": "https://www.pcbk.ru",
        "tags": ["gofra", "гофрокартон", "производитель"],
        "trust_seed": 0.84,
    },
    {
        "name": "Илим Гофра",
        "role": "manufacturer",
        "city": "Москва",
        "region": "Ленинградская область",
        "website": "https://www.ilimgroup.ru",
        "tags": ["gofra", "гофрокартон", "производитель"],
        "trust_seed": 0.85,
    },
    {
        "name": "Картонтара",
        "role": "manufacturer",
        "city": "Москва",
        "region": "Московская область",
        "website": "https://www.kartontara.ru",
        "tags": ["gofra", "гофроящик", "производитель"],
        "trust_seed": 0.8,
    },
    {
        "name": "ГОФРОМАСТЕР",
        "role": "dealer",
        "city": "Москва",
        "region": "Москва",
        "website": "https://gofromaster.ru",
        "tags": ["gofra", "гофрокороб", "дилер", "москва"],
        "trust_seed": 0.75,
        "notes": "Поставки гофрокоробов в Москве и области",
    },
    {
        "name": "УпакМастер",
        "role": "dealer",
        "city": "Москва",
        "region": "Москва",
        "website": "https://upakmaster.ru",
        "tags": ["gofra", "упаковка", "дилер", "москва"],
        "trust_seed": 0.72,
    },
    {
        "name": "Коробкин",
        "role": "dealer",
        "city": "Москва",
        "region": "Москва",
        "website": "https://korobkin.ru",
        "tags": ["gofra", "гофрокороб", "дилер"],
        "trust_seed": 0.7,
    },
    {
        "name": "ПакМаркет",
        "role": "dealer",
        "city": "Москва",
        "region": "Москва",
        "website": "https://pakmarket.ru",
        "tags": ["gofra", "упаковка", "дилер"],
        "trust_seed": 0.7,
    },
    {
        "name": "Гофра Трейд",
        "role": "dealer",
        "city": "Москва",
        "region": "Москва",
        "tags": ["gofra", "гофрокартон", "дилер", "москва"],
        "trust_seed": 0.68,
    },
    {
        "name": "МосГофра",
        "role": "dealer",
        "city": "Москва",
        "region": "Москва",
        "tags": ["gofra", "гофрокороб", "москва"],
        "trust_seed": 0.68,
    },
    {
        "name": "Русская гофротара",
        "role": "dealer",
        "city": "Москва",
        "region": "Москва",
        "tags": ["gofra", "гофротара", "дилер"],
        "trust_seed": 0.7,
    },
    {
        "name": "Альтпак",
        "role": "dealer",
        "city": "Москва",
        "region": "Москва",
        "website": "https://altpack.ru",
        "tags": ["gofra", "упаковка", "дилер"],
        "trust_seed": 0.72,
    },
    {
        "name": "Данафлекс",
        "role": "manufacturer",
        "city": "Москва",
        "region": "Москва",
        "website": "https://www.danaflex.ru",
        "tags": ["упаковка", "гибкая", "косметика"],
        "trust_seed": 0.78,
        "notes": "Упаковка для FMCG/косметики; смежный интерес",
    },
    {
        "name": "Мультипак",
        "role": "dealer",
        "city": "Москва",
        "region": "Москва",
        "tags": ["gofra", "гофрокороб", "дилер", "москва"],
        "trust_seed": 0.7,
    },
    {
        "name": "ПрофУпак",
        "role": "dealer",
        "city": "Москва",
        "region": "Московская область",
        "tags": ["gofra", "картонная упаковка", "дилер"],
        "trust_seed": 0.68,
    },
    {
        "name": "БоксМастер",
        "role": "dealer",
        "city": "Москва",
        "region": "Москва",
        "tags": ["gofra", "короб", "дилер"],
        "trust_seed": 0.66,
    },
    {
        "name": "ГофроПром",
        "role": "manufacturer",
        "city": "Москва",
        "region": "Московская область",
        "tags": ["gofra", "производитель", "гофрокартон"],
        "trust_seed": 0.75,
    },
    {
        "name": "КартонСервис",
        "role": "dealer",
        "city": "Москва",
        "region": "Москва",
        "tags": ["gofra", "картон", "дилер"],
        "trust_seed": 0.68,
    },
    {
        "name": "УпакПро",
        "role": "dealer",
        "city": "Москва",
        "region": "Москва",
        "tags": ["gofra", "упаковка", "косметика", "дилер"],
        "trust_seed": 0.7,
    },
    {
        "name": "ТД Гофротара",
        "role": "dealer",
        "city": "Москва",
        "region": "Москва",
        "tags": ["gofra", "гофротара", "дилер"],
        "trust_seed": 0.7,
    },
    {
        "name": "Европак",
        "role": "dealer",
        "city": "Москва",
        "region": "Москва",
        "tags": ["gofra", "упаковка", "дилер"],
        "trust_seed": 0.68,
    },
    {
        "name": "Паперпак",
        "role": "dealer",
        "city": "Москва",
        "region": "Москва",
        "tags": ["gofra", "картон", "дилер"],
        "trust_seed": 0.66,
    },
    {
        "name": "КоробОК",
        "role": "dealer",
        "city": "Москва",
        "region": "Москва",
        "tags": ["gofra", "гофрокороб", "дилер", "москва"],
        "trust_seed": 0.65,
    },
    {
        "name": "Фабрика упаковки",
        "role": "manufacturer",
        "city": "Москва",
        "region": "Московская область",
        "tags": ["gofra", "производитель", "упаковка"],
        "trust_seed": 0.74,
    },
]


def _norm_name(name: str) -> str:
    s = name.casefold().strip()
    s = re.sub(r"[«»\"']", "", s)
    s = re.sub(r"\s+", " ", s)
    return s[:512]


def seed_gofra_niche_suppliers(db: Session, *, force: bool = False) -> int:
    """Insert curated gofra suppliers if niche empty (or force upsert by name)."""
    existing = (
        db.query(NicheSupplier.id)
        .filter(NicheSupplier.niche_id == NICHE_ID, NicheSupplier.active.is_(True))
        .count()
    )
    if existing >= 15 and not force:
        return 0

    added = 0
    for row in GOFRA_MOSCOW_SEED:
        name = str(row["name"]).strip()
        nn = _norm_name(name)
        inn = row.get("inn")
        q = db.query(NicheSupplier).filter(
            NicheSupplier.niche_id == NICHE_ID,
            NicheSupplier.name_normalized == nn,
        )
        if inn:
            q = q.filter((NicheSupplier.inn == inn) | (NicheSupplier.inn.is_(None)))
        found = q.first()
        if found and not force:
            continue
        if found:
            found.role = row.get("role") or found.role
            found.city = row.get("city") or found.city
            found.region = row.get("region") or found.region
            found.website = row.get("website") or found.website
            found.email = row.get("email") or found.email
            found.phone = row.get("phone") or found.phone
            found.tags = list(row.get("tags") or found.tags or [])
            found.notes = row.get("notes") or found.notes
            found.trust_seed = float(row.get("trust_seed") or found.trust_seed or 0.7)
            found.active = True
            if inn:
                found.inn = inn
            continue
        db.add(
            NicheSupplier(
                niche_id=NICHE_ID,
                name=name,
                name_normalized=nn,
                inn=inn,
                role=str(row.get("role") or "unknown"),
                city=row.get("city"),
                region=row.get("region"),
                website=row.get("website"),
                email=row.get("email"),
                phone=row.get("phone"),
                tags=list(row.get("tags") or []),
                notes=row.get("notes"),
                trust_seed=float(row.get("trust_seed") or 0.7),
                active=True,
            )
        )
        added += 1
    if added:
        db.commit()
    return added
