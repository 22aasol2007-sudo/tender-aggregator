"""Shared helpers for freight website scrapers."""

from __future__ import annotations

import re

from app.parse import CITY_ALIASES

# ЦФО + СЗФО + ПФО region URL slugs used by Perevozka24 / CargoCash-style boards.
CFD_NWFD_PFO_REGIONS: list[str] = [
    # ЦФО
    "moskva",
    "moskovskaya-oblast",
    "belgorodskaya-oblast",
    "bryanskaya-oblast",
    "vladimirskaya-oblast",
    "voronezhskaya-oblast",
    "ivanovskaya-oblast",
    "kaluzhskaya-oblast",
    "kostromskaya-oblast",
    "kurskaya-oblast",
    "lipetskaya-oblast",
    "orlovskaya-oblast",
    "ryazanskaya-oblast",
    "smolenskaya-oblast",
    "tambovskaya-oblast",
    "tverskaya-oblast",
    "tulskaya-oblast",
    "yaroslavskaya-oblast",
    # СЗФО
    "sankt-peterburg",
    "leningradskaya-oblast",
    "arhangelskaya-oblast",
    "vologodskaya-oblast",
    "kaliningradskaya-oblast",
    "murmanskaya-oblast",
    "novgorodskaya-oblast",
    "pskovskaya-oblast",
    "respublika-kareliya",
    "respublika-komi",
    "nenetskiy-ao",
    # ПФО
    "nizhegorodskaya-oblast",
    "kirovskaya-oblast",
    "orenburgskaya-oblast",
    "penzenskaya-oblast",
    "permskiy-kraj",
    "permskaya-oblast",
    "samarskaya-oblast",
    "saratovskaya-oblast",
    "ulyanovskaya-oblast",
    "respublika-bashkortostan",
    "bashkiriya",
    "respublika-marij-el",
    "respublika-mordoviya",
    "respublika-tatarstan",
    "udmurtskaya-respublika",
    "chuvashskaya-respublika",
]

BODY_HINTS = (
    ("реф", "reefer"),
    ("холодиль", "reefer"),
    ("изотерм", "isotherm"),
    ("тент", "tent"),
    ("штор", "tent"),
    ("curtain", "tent"),
    ("борт", "board"),
    ("фургон", "box"),
    ("цельнометалл", "box"),
)


def exact_city(raw: str | None) -> str | None:
    if not raw:
        return None
    name = raw.split("(")[0].strip(" \t\r\n,.-")
    if not name:
        return None
    key = name.lower().replace("ё", "е")
    for alias, canon in CITY_ALIASES.items():
        if alias.replace("ё", "е") == key:
            return canon
    return key


def infer_body(text: str) -> str | None:
    low = (text or "").lower()
    for key, body in BODY_HINTS:
        if key in low:
            return body
    return None


def parse_tonnage(text: str) -> float | None:
    for pat in (
        r"(?:ВЕС|вес)\s*(\d+[.,]?\d*)\s*т",
        r"(\d+[.,]?\d*)\s*тн\b",
        r"(\d+[.,]?\d*)\s*т(?:онн)?\b",
        r"(\d+[.,]?\d*)\s*t\b",
    ):
        m = re.search(pat, text or "", re.I)
        if m:
            try:
                return float(m.group(1).replace(",", "."))
            except ValueError:
                return None
    return None
