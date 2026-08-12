"""Niche plugin protocol for sourcing shortlists."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass(frozen=True)
class NicheClarifyField:
    key: str
    label: str
    required: bool = False


@dataclass
class NichePluginData:
    id: str
    title: str
    default_city: str
    search_terms: list[str]
    context_terms: list[str] = field(default_factory=list)
    seed_tags: list[str] = field(default_factory=list)
    attribute_keys: list[str] = field(default_factory=list)
    clarify_fields: list[NicheClarifyField] = field(default_factory=list)
    pilot_min_share_n: int = 3
    design_partner_rules: dict[str, Any] = field(default_factory=dict)
    phase: dict[str, Any] = field(default_factory=dict)

    def normalize_attrs(self, raw: dict | None) -> dict:
        raise NotImplementedError

    def attrs_fingerprint_part(self, attrs: dict | None) -> str:
        a = self.normalize_attrs(attrs)
        if not a:
            return ""
        return "|".join(f"{k}={a[k]}" for k in sorted(a))

    def payload(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "city_default": self.default_city,
            "pilot_min_share_n": self.pilot_min_share_n,
            "attributes": list(self.attribute_keys),
            "search_terms": list(self.search_terms),
            "context_terms": list(self.context_terms),
            "seed_tags": list(self.seed_tags),
            "clarify_fields": [
                {"key": f.key, "label": f.label, "required": f.required} for f in self.clarify_fields
            ],
            "design_partner_rules": self.design_partner_rules,
            "phase": self.phase,
        }


class NichePlugin(Protocol):
    id: str
    title: str
    default_city: str
    search_terms: list[str]
    seed_tags: list[str]

    def normalize_attrs(self, raw: dict | None) -> dict: ...

    def attrs_fingerprint_part(self, attrs: dict | None) -> str: ...

    def payload(self) -> dict[str, Any]: ...
