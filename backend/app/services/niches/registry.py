"""Registry of sourcing niche plugins."""

from __future__ import annotations

from app.services.niches.base import NichePlugin
from app.services.niches.gofra_cosmetics import GofraCosmeticsNiche, NICHE_ID as GOFRA_ID

_REGISTRY: dict[str, NichePlugin] = {}


def _ensure() -> None:
    if _REGISTRY:
        return
    gofra = GofraCosmeticsNiche()
    _REGISTRY[gofra.id] = gofra


def get_niche(niche_id: str | None = None) -> NichePlugin:
    _ensure()
    key = (niche_id or GOFRA_ID).strip() or GOFRA_ID
    plugin = _REGISTRY.get(key)
    if plugin is None:
        # Unknown niche → fall back to gofra wedge
        return _REGISTRY[GOFRA_ID]
    return plugin


def list_niches() -> list[dict]:
    _ensure()
    return [p.payload() for p in _REGISTRY.values()]
