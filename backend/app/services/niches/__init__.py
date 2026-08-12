"""Niche plugins for sourcing shortlist / RFQ."""

from __future__ import annotations

from app.services.niches.base import NichePlugin
from app.services.niches.registry import get_niche, list_niches

__all__ = ["NichePlugin", "get_niche", "list_niches"]
