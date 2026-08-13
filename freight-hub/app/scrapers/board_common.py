"""Shared helpers for freight website scrapers."""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

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

MSK = timezone(timedelta(hours=3))


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


def _max_age_sec() -> float:
    try:
        from app import config

        return float(getattr(config, "MAX_LOAD_AGE_SEC", 7 * 86400))
    except Exception:
        return 7 * 86400


def parse_iso_datetime(value: str | None, *, now: float | None = None) -> float | None:
    """Parse ISO-8601 / unix ms-or-s into unix seconds. Rejects outside MAX_LOAD_AGE."""
    import time as _time

    raw = (value or "").strip()
    if not raw:
        return None
    ref = now if now is not None else _time.time()
    try:
        if re.fullmatch(r"\d{10,13}", raw):
            ts = float(raw)
            if ts > 1e12:
                ts /= 1000.0
        else:
            cleaned = raw.replace("Z", "+00:00")
            dt = datetime.fromisoformat(cleaned)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=MSK)
            ts = dt.timestamp()
    except Exception:
        return None
    if ts > ref + 2 * 86400 or ts < ref - _max_age_sec():
        return None
    return ts


def parse_posted_at_ru(text: str, *, now: float | None = None) -> float | None:
    """Parse board timestamps like '31.07 11:43' or '31.07.2026 11:43' → unix seconds.

    Rejects timestamps older than MAX_LOAD_AGE (default 7 days).
    Skips dates glued to погрузка/выгрузка labels (those are load dates, not publish time).
    Board wall-clock is treated as Europe/Moscow.
    """
    import time as _time

    raw = text or ""
    m = re.search(
        r"\b(\d{1,2})\.(\d{1,2})(?:\.(\d{2,4}))?\s+(\d{1,2}):(\d{2})\b",
        raw,
    )
    if not m:
        iso = re.search(
            r"\b(\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}(?::\d{2})?(?:Z|[+-]\d{2}:?\d{2})?)\b",
            raw,
        )
        if iso:
            return parse_iso_datetime(iso.group(1), now=now)
        return None

    prefix = raw[max(0, m.start() - 28) : m.start()].lower()
    if re.search(r"(погрузк|выгрузк|загрузк)\w*\s*[:=]?\s*$", prefix):
        return None

    day = int(m.group(1))
    month = int(m.group(2))
    year_raw = m.group(3)
    hour = int(m.group(4))
    minute = int(m.group(5))
    if not (1 <= day <= 31 and 1 <= month <= 12 and 0 <= hour <= 23 and 0 <= minute <= 59):
        return None
    ref = now if now is not None else _time.time()
    ref_dt = datetime.fromtimestamp(ref)
    if year_raw:
        year = int(year_raw)
        if year < 100:
            year += 2000
        if year < ref_dt.year - 1:
            return None
    else:
        year = ref_dt.year
        try:
            candidate = datetime(year, month, day, hour, minute, tzinfo=MSK)
        except ValueError:
            return None
        if candidate.timestamp() > ref + 2 * 86400:
            year -= 1
    try:
        dt = datetime(year, month, day, hour, minute, tzinfo=MSK)
    except ValueError:
        return None
    ts = dt.timestamp()
    if ts > ref + 2 * 86400 or ts < ref - _max_age_sec():
        return None
    return ts
