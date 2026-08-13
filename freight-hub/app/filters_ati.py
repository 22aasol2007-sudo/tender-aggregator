"""ATI-inspired filter helpers for freight-hub feed."""

from __future__ import annotations

import time
from datetime import datetime
from typing import Any


LOADING_PATTERNS = {
    "rear": (r"задн", r"сзади", r"задняя"),
    "side": (r"боков", r"сбоку", r"боковая"),
    "top": (r"верхн", r"сверху", r"верхняя"),
}

LTL_PATTERNS = (r"догруз", r"частичн", r"ltl", r"сборн")
FTL_PATTERNS = (r"отдельн\w*\s+авто", r"фул\s*трак", r"ftl", r"полная\s+загруз")

PAY_PATTERNS = {
    "cash": (r"налич", r"\bнал\b", r"кэш"),
    "nds": (r"с\s*ндс", r"ндс"),
    "no_nds": (r"без\s*ндс", r"б/?н\s*без"),
    "prepay": (r"предоплат", r"аванс"),
}


def clamp_tonnage_band(
    tonnage_min: float | None,
    tonnage_max: float | None,
    *,
    hard_min: float,
    hard_max: float,
) -> tuple[float, float]:
    lo = hard_min if tonnage_min is None else max(hard_min, float(tonnage_min))
    hi = hard_max if tonnage_max is None else min(hard_max, float(tonnage_max))
    if lo > hi:
        lo, hi = hard_min, hard_max
    return lo, hi


def load_date_window(mode: str | None, *, now: float | None = None) -> tuple[float | None, float | None]:
    """Return (created_at_min, created_at_max) soft window for load-date presets.

    We don't always have structured load_date, so for today/tomorrow/3d we use
    created_at proximity as a practical proxy, plus text match applied separately.
    """
    if not mode or mode in {"any", "all", ""}:
        return None, None
    ref = now if now is not None else time.time()
    dt = datetime.fromtimestamp(ref)
    start_today = datetime(dt.year, dt.month, dt.day).timestamp()
    if mode == "today":
        return start_today, start_today + 86400
    if mode == "tomorrow":
        return start_today + 86400, start_today + 2 * 86400
    if mode in {"3d", "days3"}:
        return start_today, start_today + 3 * 86400
    if mode == "week":
        return start_today, start_today + 7 * 86400
    return None, None


def freshness_cutoff(hours: float | None, *, now: float | None = None) -> float | None:
    if hours is None or hours <= 0:
        return None
    ref = now if now is not None else time.time()
    return ref - float(hours) * 3600


def append_ati_filters(
    sql: list[str],
    args: list[Any],
    *,
    tonnage_min: float | None = None,
    tonnage_max: float | None = None,
    volume_min: float | None = None,
    volume_max: float | None = None,
    ppk_min: float | None = None,
    price_min: float | None = None,
    route_km_min: float | None = None,
    route_km_max: float | None = None,
    freshness_hours: float | None = None,
    load_date_mode: str | None = None,
    loading: str | None = None,
    cargo_mode: str | None = None,
    payment: str | None = None,
    exact_from: bool = False,
    exact_to: bool = False,
    from_city: str | None = None,
    to_city: str | None = None,
    hard_tonnage_min: float = 5.0,
    hard_tonnage_max: float = 12.0,
    now: float | None = None,
) -> None:
    """Append ATI-like WHERE clauses (mutates sql/args)."""
    lo, hi = clamp_tonnage_band(
        tonnage_min, tonnage_max, hard_min=hard_tonnage_min, hard_max=hard_tonnage_max
    )
    sql.append("AND (tonnage IS NULL OR (tonnage >= ? AND tonnage <= ?))")
    args.extend([lo, hi])

    if volume_min is not None:
        sql.append("AND (volume_m3 IS NULL OR volume_m3 >= ?)")
        args.append(float(volume_min))
    if volume_max is not None:
        sql.append("AND (volume_m3 IS NULL OR volume_m3 <= ?)")
        args.append(float(volume_max))

    if ppk_min is not None and float(ppk_min) > 0:
        sql.append("AND price_per_km IS NOT NULL AND price_per_km >= ?")
        args.append(float(ppk_min))

    # price_min applied by caller (free-text price field)

    if route_km_min is not None:
        sql.append("AND (route_km IS NULL OR route_km >= ?)")
        args.append(float(route_km_min))
    if route_km_max is not None:
        sql.append("AND (route_km IS NULL OR route_km <= ?)")
        args.append(float(route_km_max))

    cut = freshness_cutoff(freshness_hours, now=now)
    if cut is not None:
        sql.append("AND created_at >= ?")
        args.append(cut)

    d0, d1 = load_date_window(load_date_mode, now=now)
    if load_date_mode in {"today", "tomorrow", "3d", "days3", "week"}:
        # Text cues in load_date/body + created_at window as soft OR
        labels: list[str] = []
        if load_date_mode == "today":
            labels = ["сегодня", "сегодня-", "на сегодня"]
        elif load_date_mode == "tomorrow":
            labels = ["завтра", "на завтра"]
        elif load_date_mode in {"3d", "days3"}:
            labels = ["сегодня", "завтра"]
        ors = []
        if d0 is not None and d1 is not None:
            ors.append("(created_at >= ? AND created_at < ?)")
            args.extend([d0, d1])
        for lab in labels:
            ors.append("LOWER(COALESCE(load_date,'')) LIKE ?")
            args.append(f"%{lab}%")
            ors.append("LOWER(COALESCE(body,'')) LIKE ?")
            args.append(f"%{lab}%")
        if ors:
            sql.append("AND (" + " OR ".join(ors) + ")")

    loading_key = (loading or "").strip().lower()
    if loading_key in LOADING_PATTERNS:
        pats = LOADING_PATTERNS[loading_key]
        sql.append(
            "AND (" + " OR ".join(["LOWER(COALESCE(body,'')) LIKE ?"] * len(pats)) + ")"
        )
        args.extend([f"%{p}%" for p in pats])

    mode = (cargo_mode or "").strip().lower()
    if mode == "ltl":
        sql.append(
            "AND (" + " OR ".join(["LOWER(COALESCE(body,'')) LIKE ?"] * len(LTL_PATTERNS)) + ")"
        )
        args.extend([f"%{p}%" for p in LTL_PATTERNS])
    elif mode == "ftl":
        # Prefer explicit FTL markers OR exclude obvious LTL
        sql.append(
            "AND NOT ("
            + " OR ".join(["LOWER(COALESCE(body,'')) LIKE ?"] * len(LTL_PATTERNS))
            + ")"
        )
        args.extend([f"%{p}%" for p in LTL_PATTERNS])

    pay = (payment or "").strip().lower()
    if pay in PAY_PATTERNS:
        pats = PAY_PATTERNS[pay]
        sql.append(
            "AND ("
            + " OR ".join(
                ["LOWER(COALESCE(body,'')) LIKE ?", "LOWER(COALESCE(price,'')) LIKE ?"] * len(pats)
            )
            + ")"
        )
        for p in pats:
            like = f"%{p}%"
            args.extend([like, like])
    elif pay == "with_rate":
        sql.append(
            "AND ("
            "price IS NOT NULL AND TRIM(price) != '' "
            "OR price_per_km IS NOT NULL"
            ")"
        )

    if exact_from and from_city:
        sql.append("AND LOWER(COALESCE(from_city,'')) = ?")
        args.append(from_city.lower().strip())
    if exact_to and to_city:
        sql.append("AND LOWER(COALESCE(to_city,'')) = ?")
        args.append(to_city.lower().strip())
