"""Niche defaults: refrigerated + general cargo transport."""

from __future__ import annotations

# OR-terms (comma-separated in TRANSPORT_Q). Multi-word = phrase match.
# Avoid broad single tokens like «груз», «по», «услуг».
TRANSPORT_INCLUDE_TERMS: list[str] = [
    # Рефрижератор / холодная цепь
    "рефрижератор",
    "рефтранспорт",
    "хладотранспорт",
    "изотерм",
    "температурный режим",
    "температурн",
    "скоропортящ",
    "холодовая цепь",
    "холодная цепь",
    "охлаждённ",
    "охлажденн",
    "замороженн",
    "рефрижераторн",
    "reefer",
    # Общие грузоперевозки
    "грузоперевоз",
    "перевозка грузов",
    "перевозки грузов",
    "перевозку грузов",
    "автоперевоз",
    "доставка грузов",
    "доставке грузов",
    "транспортные услуги",
    "транспортных услуг",
    "транспортно-экспедиц",
    "экспедирован",
    "экспедиторск",
    "фрахт",
    "логистическ",
    "логистик",
    "автотранспортн",
    "грузовым автомобил",
    "автомобильным транспортом",
    "перевозка продукции",
    "перевозки продукции",
    "перевозка товаров",
    "перевозки товаров",
    "услуги по перевозке",
    "оказание услуг по перевозке",
    "контейнерные перевоз",
    "контейнерных перевоз",
    "тентованн",
    "негабаритн",
    "сборных грузов",
    "сборный груз",
    # ОКПД2
    "49.41",
    "49.4",
    "52.29",
]

TRANSPORT_EXCLUDE_TERMS: list[str] = [
    "программное обеспечение",
    "разработка сайта",
    "лицензия ПО",
    "антивирус",
    "серверное оборудование",
    "оргтехника",
    "канцеляр",
    "офисная мебель",
    "уборка помещений",
    "охранные услуги",
]

# Comma-separated so phrases stay intact in split_terms()
TRANSPORT_Q = ", ".join(TRANSPORT_INCLUDE_TERMS)
TRANSPORT_EXCLUDE = ", ".join(TRANSPORT_EXCLUDE_TERMS)

TRANSPORT_PRESET_FILTERS: dict = {
    "q": TRANSPORT_Q,
    "exclude": TRANSPORT_EXCLUDE,
    "match_any": True,
    "status_norm": "accepting",
    "hide_outdated": True,
    "hide_duplicates": True,
}

TRANSPORT_PROFILE_KEYWORDS: list[str] = [
    "рефрижератор",
    "грузоперевоз",
    "перевозка грузов",
    "логистик",
    "хладотранспорт",
    "изотерм",
    "экспедиц",
    "автоперевоз",
    "49.41",
]

TRANSPORT_PROFILE_OKPD: list[str] = ["49.41", "49.4", "52.29", "52.2"]

# Legacy IT keywords — used to detect profiles that still need migration
LEGACY_IT_KEYWORDS = {"программ", "сервер", "строитель", "ремонт", "ИТ", "ит"}
