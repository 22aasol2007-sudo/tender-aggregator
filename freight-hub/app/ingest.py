from __future__ import annotations

import re
import time
from typing import Any

from app import config
from app.db import HubDB, make_fingerprint, make_route_fingerprint
from app.models import RawLoad
from app.parse import parse_load, parse_load_blocks
from app.score import score_load


DEFAULT_USER = {
    "mode": "shipper",
    "custom_keywords": "[]",
    "mute_driver_offers": 1,
    "only_reefer": 0,
    "truck_profile": '{"base":"москва","radius":150,"radius_far":1500}',
    "directions": "[]",
}


HARD_GEO_SKIP = {
    "far_leg_too_far",
    "outside_far_radius",
    "no_near_leg",
    "not_backhaul",
    "backhaul_no_to",
    "backhaul_unknown_geo",
    "no_route",
    "geo_unknown",
    "incomplete_route",
}

ARCHIVE_RE = re.compile(
    r"(?:\bзаверш[её]н(?:о|а|ы)?\b|\bв архиве\b|\bархивн\w*\b|"
    r"\bснят с публикации\b|\bзаказ выполнен\b|\bудал[её]н[оа]?\s+с\s+доски\b)",
    re.I,
)

# Board-specific closed markers (status chips / labels, not free text noise)
BOARD_CLOSED_RE = re.compile(
    r"(?:класс=\"[^\"]*(?:completed|archive|closed|done)[^\"]*\"|"
    r"data-status=\"(?:completed|closed|archive|done)\"|"
    r">\s*(?:заверш[её]н|архив|снято)\s*<)",
    re.I,
)

# "62000", "62 000 руб", "62тыс", "1200₽/км" (last is already per-km — skip dividing)
_PRICE_NUM_RE = re.compile(r"(\d[\d\s]{2,12}|\d+(?:[.,]\d+)?)", re.I)


def is_archived_text(text: str | None) -> bool:
    if not text:
        return False
    if BOARD_CLOSED_RE.search(text):
        return True
    return bool(ARCHIVE_RE.search(text))


def parse_price_rub(price: str | None) -> float | None:
    """Parse human price string into total RUB amount (not per-km)."""
    if not price:
        return None
    raw = str(price).strip().lower().replace("\xa0", " ")
    if not raw:
        return None
    # Already per-km — don't treat as total haul price
    if "/км" in raw or "за км" in raw or "руб/км" in raw or "₽/км" in raw:
        return None
    m = _PRICE_NUM_RE.search(raw.replace(" ", ""))
    if not m:
        m = _PRICE_NUM_RE.search(raw)
    if not m:
        return None
    try:
        val = float(m.group(1).replace(" ", "").replace(",", "."))
    except ValueError:
        return None
    if val <= 0:
        return None
    if "тыс" in raw or "т.р" in raw or re.search(r"\bтр\b", raw):
        if val < 1000:
            val *= 1000
    # Ignore tiny numbers that are likely not freight rates
    if val < 1000:
        return None
    return val


def calc_price_per_km(
    price: str | None,
    from_city: str | None,
    to_city: str | None,
) -> tuple[float | None, float | None]:
    """Return (route_km, rub_per_km) when both price and distance are known."""
    amount = parse_price_rub(price)
    if amount is None:
        return None, None
    try:
        from freight_core.geo import distance_km

        route_km = distance_km(from_city, to_city)
    except Exception:
        route_km = None
    if route_km is None or route_km < 5:
        return route_km, None
    return round(route_km, 1), round(amount / route_km, 1)


def is_junk_route(from_city: str | None, to_city: str | None, *, source: str = "") -> bool:
    """Drop pseudo-routes that confuse the feed (same city both ends)."""
    a = (from_city or "").strip().lower()
    b = (to_city or "").strip().lower()
    if a and b and a == b:
        return True
    return False


def _km_to_base(city: str | None, base: str = "москва") -> float | None:
    try:
        from freight_core.geo import distance_km

        return distance_km(city, (base or "москва").strip().lower() or "москва")
    except Exception:
        return None


def _profile_base(profile_user: dict[str, Any]) -> str:
    import json as _json

    raw = profile_user.get("truck_profile")
    prof: dict[str, Any] = {}
    if isinstance(raw, dict):
        prof = raw
    elif isinstance(raw, str) and raw.strip():
        try:
            parsed = _json.loads(raw)
            if isinstance(parsed, dict):
                prof = parsed
        except Exception:
            pass
    base = str(prof.get("base") or "москва").strip().lower()
    return base or "москва"


async def recompute_km_from_base(db: HubDB, base: str | None = None) -> dict[str, int]:
    """Recalculate km_from/km_to for all loads relative to truck base city."""
    import json as _json

    if not base:
        raw = await db.get_setting("truck_profile")
        try:
            prof = _json.loads(raw) if raw else {}
        except Exception:
            prof = {}
        base = str((prof or {}).get("base") or "москва").strip().lower() or "москва"
    assert db._db is not None
    cur = await db._db.execute("SELECT id, from_city, to_city FROM loads")
    rows = await cur.fetchall()
    updated = 0
    for r in rows:
        kf = _km_to_base(r["from_city"], base)
        kt = _km_to_base(r["to_city"], base)
        await db._db.execute(
            "UPDATE loads SET km_from=?, km_to=? WHERE id=?",
            (kf, kt, r["id"]),
        )
        updated += 1
    await db._db.commit()
    return {"updated": updated, "base": base}


def why_rank(
    *,
    score: int,
    km_from: float | None,
    km_to: float | None,
    near_km: float,
    source: str,
    scraped_at: float | None,
) -> list[str]:
    out: list[str] = []
    if score >= 85:
        out.append("очень высокий скор")
    elif score >= 70:
        out.append("высокий скор")
    if km_from is not None and km_from <= near_km:
        out.append("погрузка у базы")
    elif km_to is not None and km_to <= near_km:
        out.append("выгрузка у базы")
    if source in {"telegram", "max"}:
        out.append("из мессенджера")
    if scraped_at and time.time() - float(scraped_at) <= 300:
        out.append("только что")
    return out[:3]


async def _persist(
    db: HubDB,
    raw: RawLoad,
    parsed,
    *,
    min_score: int,
    scoring: str,
    profile_user: dict[str, Any],
) -> str:
    if is_archived_text(raw.body) or is_archived_text(raw.title):
        return "skipped"
    result = score_load(parsed, profile_user, min_score=min_score, scoring=scoring)
    if result.reason in HARD_GEO_SKIP:
        return "skipped"
    if scoring == "strict" and not result.ok:
        return "skipped"

    from_city = raw.from_city or parsed.from_city
    to_city = raw.to_city or parsed.to_city
    if is_junk_route(from_city, to_city, source=raw.source):
        return "skipped"

    score = result.score
    if scoring == "browse" and raw.source not in {"telegram", "tg_public", "max"} and (
        from_city or to_city
    ):
        score = max(score, 45)

    tonnage = raw.tonnage if raw.tonnage is not None else parsed.tonnage
    fp = make_fingerprint(
        raw.source,
        from_city or "",
        to_city or "",
        str(tonnage or ""),
        (raw.body or "")[:200],
    )
    route_fp = make_route_fingerprint(from_city, to_city, tonnage, parsed.load_date)
    # Cross-source dedup: same route/day already ingested recently
    if from_city and to_city and route_fp:
        dup = await db.find_route_dup(
            route_fp,
            exclude_source=raw.source,
            exclude_external_id=str(raw.external_id),
            within_sec=config.CROSS_DEDUP_HOURS * 3600,
        )
        if dup and int(dup.get("score") or 0) >= score:
            return "skipped"

    km_from = _km_to_base(from_city, _profile_base(profile_user))
    km_to = _km_to_base(to_city, _profile_base(profile_user))
    price = raw.price or parsed.price
    route_km, price_per_km = calc_price_per_km(price, from_city, to_city)
    title = raw.title
    if from_city or to_city:
        title = f"{from_city or '?'} → {to_city or '?'}"
    item: dict[str, Any] = {
        "source": raw.source,
        "external_id": str(raw.external_id),
        "title": title or (raw.body[:80] if raw.body else ""),
        "body": raw.body,
        "from_city": from_city,
        "to_city": to_city,
        "tonnage": tonnage,
        "volume_m3": raw.volume_m3 if raw.volume_m3 is not None else parsed.volume_m3,
        "body_type": raw.body_type or parsed.body,
        "temps": raw.temps or parsed.temps,
        "price": price,
        "load_date": parsed.load_date,
        "phones": parsed.phones or [],
        "contacts": parsed.contacts or [],
        "url": raw.url,
        "score": score,
        "kind": parsed.kind,
        "fingerprint": fp,
        "route_fp": route_fp,
        "km_from": km_from,
        "km_to": km_to,
        "route_km": route_km,
        "price_per_km": price_per_km,
        "raw_json": raw.raw,
        "score_ok": 1 if result.ok else 0,
    }
    status = await db.upsert_load(item)
    if status == "added":
        if raw.source in {"telegram", "max"}:
            await db.set_setting(f"last_ingest_{raw.source}", str(time.time()))
        try:
            from app.alerts import maybe_alert_hot

            await maybe_alert_hot(item)
        except Exception:
            pass
    return status


async def ingest_raw(
    db: HubDB,
    raw: RawLoad,
    min_score: int = 0,
    *,
    scoring: str = "browse",
    user: dict[str, Any] | None = None,
    split_blocks: bool = True,
) -> str:
    """
    scoring=browse — store for web feed.
    scoring=strict — skip if ScoreResult.ok is false.
    Multi-route TG posts are split into separate loads when split_blocks=True.
    """
    if is_archived_text(raw.body) or is_archived_text(raw.title):
        return "skipped"
    profile_user = {**DEFAULT_USER, **(user or {})}
    if not user:
        try:
            saved = await db.get_setting("truck_profile")
            if saved:
                profile_user["truck_profile"] = saved
        except Exception:
            pass

    if raw.from_city or raw.to_city or not split_blocks:
        parsed = parse_load(raw.body)
        if raw.from_city:
            parsed.from_city = raw.from_city.lower()
        if raw.to_city:
            parsed.to_city = raw.to_city.lower()
        if raw.tonnage is not None:
            parsed.tonnage = raw.tonnage
        if raw.volume_m3 is not None:
            parsed.volume_m3 = raw.volume_m3
        if raw.body_type:
            parsed.body = raw.body_type
        if raw.temps:
            parsed.temps = raw.temps
        if raw.price and not parsed.price:
            parsed.price = raw.price
        return await _persist(
            db, raw, parsed, min_score=min_score, scoring=scoring, profile_user=profile_user
        )

    blocks = parse_load_blocks(raw.body)
    statuses: list[str] = []
    for i, parsed in enumerate(blocks):
        part = RawLoad(
            source=raw.source,
            external_id=f"{raw.external_id}#{i}" if len(blocks) > 1 else str(raw.external_id),
            title=raw.title,
            body=parsed.text,
            from_city=parsed.from_city,
            to_city=parsed.to_city,
            tonnage=parsed.tonnage,
            volume_m3=parsed.volume_m3,
            body_type=parsed.body,
            temps=parsed.temps,
            price=parsed.price or raw.price,
            url=raw.url,
            raw={**(raw.raw or {}), "block": i, "blocks": len(blocks)}
            if isinstance(raw.raw, dict) or raw.raw is None
            else {"block": i, "parent": raw.raw},
        )
        statuses.append(
            await _persist(
                db, part, parsed, min_score=min_score, scoring=scoring, profile_user=profile_user
            )
        )
    if any(s == "added" for s in statuses):
        return "added"
    if any(s == "updated" for s in statuses):
        return "updated"
    if all(s == "skipped" for s in statuses):
        return "skipped"
    return statuses[-1] if statuses else "skipped"
