"""Primary GTM niche: cosmetics companies in Moscow × corrugated packaging.

Thin re-export — implementation lives in app.services.niches.gofra_cosmetics.
"""

from __future__ import annotations

from app.services.niches.gofra_cosmetics import (  # noqa: F401
    COSMETICS_CONTEXT_TERMS,
    DEFAULT_MIN_SHARE_N,
    DESIGN_PARTNER_RULES,
    GOFRA_ATTRIBUTES,
    GOFRA_SEARCH_TERMS,
    NICHE_CITY_DEFAULT,
    NICHE_ID,
    NICHE_TITLE,
    PILOT_MIN_SHARE_N,
    attrs_fingerprint_part,
    niche_payload,
    normalize_gofra_attrs,
)

__all__ = [
    "COSMETICS_CONTEXT_TERMS",
    "DEFAULT_MIN_SHARE_N",
    "DESIGN_PARTNER_RULES",
    "GOFRA_ATTRIBUTES",
    "GOFRA_SEARCH_TERMS",
    "NICHE_CITY_DEFAULT",
    "NICHE_ID",
    "NICHE_TITLE",
    "PILOT_MIN_SHARE_N",
    "attrs_fingerprint_part",
    "niche_payload",
    "normalize_gofra_attrs",
]
