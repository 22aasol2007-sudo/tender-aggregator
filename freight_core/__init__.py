"""Shared freight parsing, scoring, geo, and chat defaults for hub + bot."""

from __future__ import annotations

from freight_core.defaults import (
    DEFAULT_CHATS,
    DRIVER_OFFER_KEYWORDS,
    INCLUDE_KEYWORDS,
    PRESETS,
    PUBLIC_TG_CHANNELS,
)
from freight_core.geo import CITY_COORDS, distance_km, geo_filter, parse_profile_geo
from freight_core.models import RawLoad
from freight_core.parse import ParsedLoad, city_search_terms, parse_load
from freight_core.score import ScoreResult, format_card_html, format_full_html, score_load

__all__ = [
    "DEFAULT_CHATS",
    "DRIVER_OFFER_KEYWORDS",
    "INCLUDE_KEYWORDS",
    "PRESETS",
    "PUBLIC_TG_CHANNELS",
    "CITY_COORDS",
    "distance_km",
    "geo_filter",
    "parse_profile_geo",
    "RawLoad",
    "ParsedLoad",
    "city_search_terms",
    "parse_load",
    "ScoreResult",
    "format_card_html",
    "format_full_html",
    "score_load",
]
