from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class RawLoad:
    source: str
    external_id: str
    body: str
    title: str | None = None
    from_city: str | None = None
    to_city: str | None = None
    tonnage: float | None = None
    volume_m3: float | None = None
    body_type: str | None = None
    temps: list[str] = field(default_factory=list)
    price: str | None = None
    url: str | None = None
    # Original board/messenger publish time (unix seconds), when known
    posted_at: float | None = None
    raw: dict[str, Any] | None = None
