"""Score parsed loads against user profile / filters."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from freight_core.geo import geo_filter, parse_profile_geo
from freight_core.parse import ParsedLoad


@dataclass
class ScoreResult:
    ok: bool
    score: int
    reason: str
    matched: list[str]


def _profile(user: dict[str, Any]) -> dict[str, Any]:
    try:
        p = json.loads(user.get("truck_profile") or "{}")
    except json.JSONDecodeError:
        p = {}
    return p if isinstance(p, dict) else {}


def _dirs(user: dict[str, Any]) -> list[str]:
    try:
        d = json.loads(user.get("directions") or "[]")
    except json.JSONDecodeError:
        d = []
    return [str(x).lower() for x in d] if isinstance(d, list) else []


def score_load(
    parsed: ParsedLoad,
    user: dict[str, Any],
    min_score: int,
    *,
    scoring: str = "strict",
) -> ScoreResult:
    """
    scoring=strict — alerts (require strong signal, respect min_score).
    scoring=browse — hub feed (keep weak-but-useful rows; still mute noise/drivers).
    """
    if parsed.kind == "noise":
        return ScoreResult(False, 0, "noise", [])

    mute_drivers = bool(user.get("mute_driver_offers", 1))
    if mute_drivers and parsed.kind == "driver":
        return ScoreResult(False, 0, "driver_offer", [])

    only_reefer = bool(user.get("only_reefer"))
    profile = _profile(user)
    body_pref = (profile.get("body") or "").lower()

    reeferish = (
        parsed.body in {"reefer", "isotherm"}
        or bool(parsed.temps)
        or any(x in parsed.norm for x in ("реф", "изотерм", "температур", "замороз", "охлажд"))
    )
    if only_reefer and not reeferish:
        return ScoreResult(False, 0, "not_reefer", [])

    radius_km, far_radius_km, backhaul_only = parse_profile_geo(profile)
    base = (profile.get("base") or "").lower() or None
    geo_ok, geo_reason, geo_matched = geo_filter(
        base=base,
        from_city=parsed.from_city,
        to_city=parsed.to_city,
        radius_km=radius_km,
        far_radius_km=far_radius_km,
        backhaul_only=backhaul_only,
    )
    if not geo_ok:
        return ScoreResult(False, 0, geo_reason, geo_matched)

    score = 0
    matched: list[str] = list(geo_matched)

    if parsed.kind == "shipper":
        score += 40
        matched.append("грузовладелец")
    elif parsed.kind == "mixed":
        score += 28
        matched.append("смешанный")
    elif parsed.kind == "other":
        score += 5
    elif parsed.kind == "driver":
        score += 0

    if parsed.from_city or parsed.to_city:
        score += 20
        route = f"{parsed.from_city or '?'}→{parsed.to_city or '?'}"
        matched.append(route)

    if parsed.tonnage is not None:
        score += 12
        matched.append(f"{parsed.tonnage:g}т")
        pref_t = profile.get("tonnage")
        if pref_t:
            try:
                pt = float(pref_t)
                if abs(parsed.tonnage - pt) <= 5 or parsed.tonnage <= pt + 2:
                    score += 8
                    matched.append("тоннаж≈профиль")
            except (TypeError, ValueError):
                pass

    if parsed.volume_m3 is not None:
        score += 6
        matched.append(f"{parsed.volume_m3:g}м³")

    if parsed.body:
        score += 10
        matched.append(parsed.body)
        if body_pref and parsed.body == body_pref:
            score += 12
            matched.append("кузов=профиль")
        elif body_pref == "reefer" and parsed.body in {"reefer", "isotherm"}:
            score += 10

    if parsed.temps:
        score += 12
        matched.append("темп:" + ",".join(parsed.temps[:3]))

    dirs = _dirs(user)
    if dirs:
        blob = " ".join(
            x
            for x in (
                parsed.from_city,
                parsed.to_city,
                parsed.norm,
            )
            if x
        )
        if any(d in blob for d in dirs):
            score += 15
            matched.append("направление")
        else:
            if parsed.from_city or parsed.to_city:
                score -= 10

    if base and (
        base in (parsed.from_city or "")
        or base in (parsed.to_city or "")
        or base in parsed.norm
    ):
        score += 10
        if "база" not in matched:
            matched.append("база")

    try:
        custom = json.loads(user.get("custom_keywords") or "[]")
    except json.JSONDecodeError:
        custom = []
    if isinstance(custom, list):
        for kw in custom:
            k = str(kw).lower().strip()
            if k and k in parsed.norm:
                score += 5
                matched.append(k)

    mode = user.get("mode") or "shipper"
    if mode == "reefer" and (parsed.body in {"reefer", "isotherm"} or parsed.temps):
        score += 8
    if mode == "tent" and parsed.body == "tent":
        score += 8
    if mode == "my_truck":
        score += 5

    # Browse soft floors (modest) — never invent shipper score for drivers/noise
    if scoring == "browse":
        if parsed.kind in {"shipper", "mixed"}:
            score = max(score, 40)
        elif parsed.from_city or parsed.to_city:
            score = max(score, 28)

    score = max(0, min(100, score))

    strong = (
        parsed.kind in {"shipper", "mixed"}
        or (parsed.from_city and parsed.to_city and (parsed.tonnage or parsed.body))
    )
    if scoring == "strict" and not strong:
        return ScoreResult(False, score, "weak_signal", matched)

    if score < min_score:
        return ScoreResult(False, score, "below_threshold", matched)
    return ScoreResult(True, score, "ok", matched[:10])


def format_card_html(
    *,
    chat_title: str,
    chat_username: str | None,
    parsed: ParsedLoad,
    score: int,
    msg_link: str | None,
) -> str:
    """Compact card: route · t · body · temp · score · link."""
    chat = f"@{chat_username}" if chat_username else chat_title
    route = f"{parsed.from_city or '?'} → {parsed.to_city or '?'}"
    parts = [route]
    if parsed.tonnage is not None:
        parts.append(f"{parsed.tonnage:g}т")
    if parsed.volume_m3 is not None:
        parts.append(f"{parsed.volume_m3:g}м³")
    if parsed.body:
        parts.append(parsed.body)
    if parsed.temps:
        parts.append(" ".join(parsed.temps[:3]))
    if getattr(parsed, "price", None):
        parts.append(str(parsed.price))
    if getattr(parsed, "load_date", None):
        parts.append(str(parsed.load_date))
    line = " · ".join(parts)
    out = [
        f"📦 <b>{_esc(chat_title)}</b> · <b>{score}</b>/100",
        _esc(line),
        f"<i>{_esc(chat)}</i>",
    ]
    phones = getattr(parsed, "phones", None) or []
    contacts = getattr(parsed, "contacts", None) or []
    if phones or contacts:
        out.append(_esc(" · ".join([*phones[:2], *[f"@{c}" for c in contacts[:2]]])))
    if msg_link:
        out.append(f'<a href="{_esc(msg_link)}">Открыть в чате</a>')
    return "\n".join(out)


def format_full_html(text: str, max_chars: int = 3500) -> str:
    body = (text or "").strip()
    if len(body) > max_chars:
        body = body[: max_chars - 1] + "…"
    return _esc(body)


def _esc(s: str) -> str:
    return (
        (s or "")
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )
