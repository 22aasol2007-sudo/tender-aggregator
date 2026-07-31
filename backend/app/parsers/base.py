from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol


@dataclass
class ParsedTender:
    external_id: str
    source: str
    title: str
    url: str
    law: str | None = None
    customer: str | None = None
    customer_inn: str | None = None
    region: str | None = None
    price: float | None = None
    currency: str = "RUB"
    status: str | None = None
    method: str | None = None
    okpd2: str | None = None
    description: str | None = None
    documents: list | None = None
    lots: list | None = None
    published_at: datetime | None = None
    deadline_at: datetime | None = None
    extra: dict = field(default_factory=dict)


class TenderParser(Protocol):
    source: str
    display_name: str

    async def fetch(self) -> list[ParsedTender]:
        ...
