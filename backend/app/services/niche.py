"""Niche defaults: refrigerated + general cargo transport."""

from __future__ import annotations

# High-recall default for UI (stems + phrases + OKPD). Avoid ultra-broad «груз».
# Multi-word phrases are AND-of-words; OKPD matches okpd2 only.
# OKPD first; cargo stems; phrases; skip bare «логистик» (use «логистическ»).
TRANSPORT_SHORT_TERMS: list[str] = [
    "49.41",
    "49.4",
    "52.29",
    "грузоперевоз",
    "перевоз",
    "рефрижератор",
    "автоперевоз",
    "экспедиц",
    "изотерм",
    "хладотранспорт",
    "логистическ",
    "перевозка грузов",
    "доставка грузов",
    "транспортные услуги",
    "транспортно-экспедиц",
    "услуги грузового транспорта",
]

# OR-terms (comma-separated in TRANSPORT_Q). Multi-word = phrase match.
# Avoid ultra-broad single tokens like «груз», «по», «услуг».
TRANSPORT_INCLUDE_TERMS: list[str] = [
    # ОКПД2 first (search prioritizes these when truncating)
    "49.41",
    "49.4",
    "52.29",
    "52.21",
    # Рефрижератор / холодная цепь
    "рефрижератор",
    "рефтранспорт",
    "хладотранспорт",
    "изотерм",
    "изотермическ",
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
    "грузоперевозк",
    "перевозка грузов",
    "перевозки грузов",
    "перевозку грузов",
    "перевозкам грузов",
    "автоперевоз",
    "автоперевозк",
    "доставка грузов",
    "доставке грузов",
    "доставки грузов",
    "транспортные услуги",
    "транспортных услуг",
    "оказание транспортных услуг",
    "транспортно-экспедиц",
    "транспортно экспедиц",
    "экспедирован",
    "экспедиторск",
    "экспедиционн",
    "фрахт",
    "логистическ",
    "автотранспортн",
    "грузовым автомобил",
    "автомобильным транспортом",
    "услуги грузового транспорта",
    "грузового автотранспорт",
    "перевозка продукции",
    "перевозки продукции",
    "перевозка товаров",
    "перевозки товаров",
    "услуги по перевозке",
    "оказание услуг по перевозке",
    "услуги перевозки",
    "контейнерные перевоз",
    "контейнерных перевоз",
    "тентованн",
    "негабаритн",
    "сборных грузов",
    "сборный груз",
    "фура",
    "еврофура",
    "трал",
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

# Separate EIS scrape passes (searchString) — high-frequency cargo terms
EIS_SEARCH_PASSES: list[str] = [
    "грузоперевоз",
    "рефрижератор",
    "перевозка грузов",
    "49.41",
]

# Comma-separated so phrases stay intact in split_terms()
TRANSPORT_SHORT_Q = ", ".join(TRANSPORT_SHORT_TERMS)
TRANSPORT_Q = ", ".join(TRANSPORT_INCLUDE_TERMS)
TRANSPORT_FULL_Q = TRANSPORT_Q
TRANSPORT_EXCLUDE = ", ".join(TRANSPORT_EXCLUDE_TERMS)

TRANSPORT_PRESET_FILTERS: dict = {
    "q": TRANSPORT_SHORT_Q,
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
    "хладотранспорт",
    "изотерм",
    "экспедиц",
    "автоперевоз",
    "49.41",
    "транспортные услуги",
]

TRANSPORT_PROFILE_OKPD: list[str] = ["49.41", "49.4", "52.29", "52.2"]

# Legacy IT keywords — used to detect profiles that still need migration
LEGACY_IT_KEYWORDS = {"программ", "сервер", "строитель", "ремонт", "ИТ", "ит"}


def niche_payload() -> dict:
    """Public GET /api/niche payload — keep FE defaults in sync."""
    return {
        "short_q": TRANSPORT_SHORT_Q,
        "full_q": TRANSPORT_FULL_Q,
        "exclude": TRANSPORT_EXCLUDE,
        "okpd": list(TRANSPORT_PROFILE_OKPD),
        "eis_search_passes": list(EIS_SEARCH_PASSES),
        # Bump when search/niche recall logic changes (deploy sanity check)
        "search_engine": "phrase-and-or-v17-orm-id-merge",
        "presets": {
            "default": {
                "name": "Грузоперевозки + реф",
                "q": TRANSPORT_SHORT_Q,
                "exclude": TRANSPORT_EXCLUDE,
                "match_any": True,
            },
            "maximum": {
                "name": "Максимум ниши",
                "q": TRANSPORT_FULL_Q,
                "exclude": TRANSPORT_EXCLUDE,
                "match_any": True,
            },
            "reefer": {
                "name": "Только рефрижератор",
                "q": (
                    "рефрижератор, рефтранспорт, хладотранспорт, изотерм, "
                    "температурный режим, скоропортящ, холодовая цепь, холодная цепь, "
                    "охлажденн, замороженн, рефрижераторн"
                ),
                "exclude": "программное обеспечение, серверное оборудование, канцеляр, офисная мебель",
                "match_any": True,
            },
        },
    }
