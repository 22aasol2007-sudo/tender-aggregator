from __future__ import annotations

from app.models import CompanyProfile, Tender


def score_tender(tender: Tender, profile: CompanyProfile | None) -> int:
    if profile is None:
        return 0
    score = 0
    title = (tender.title or "").lower()
    desc = (tender.description or "").lower()
    blob = f"{title} {desc}"

    keywords = [k.lower() for k in (profile.keywords or []) if k]
    if keywords:
        hits = sum(1 for k in keywords if k in blob)
        score += min(40, hits * 12)

    prefixes = [str(p) for p in (profile.okpd_prefixes or []) if p]
    if prefixes and tender.okpd2:
        if any(tender.okpd2.startswith(p) for p in prefixes):
            score += 30

    regions = [r.lower() for r in (profile.regions or []) if r]
    if regions and tender.region:
        if any(r in tender.region.lower() for r in regions):
            score += 20

    if tender.price is not None:
        in_min = profile.min_price is None or tender.price >= profile.min_price
        in_max = profile.max_price is None or tender.price <= profile.max_price
        if in_min and in_max:
            score += 10
        elif profile.min_price or profile.max_price:
            score -= 5

    return max(0, min(100, score))
