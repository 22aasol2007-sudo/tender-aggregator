from __future__ import annotations

import hashlib
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.models import Tender, TenderChange


TRACKED_FIELDS = ("price", "deadline_at", "status", "status_norm", "title", "region", "method")


def content_hash_for(
    title: str,
    price: float | None,
    status: str | None,
    deadline_at: datetime | None,
    region: str | None,
    method: str | None,
) -> str:
    deadline = deadline_at.isoformat() if deadline_at else ""
    raw = f"{title}|{price}|{status}|{deadline}|{region}|{method}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()


def _as_str(value) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def record_changes(db: Session, tender: Tender, before: dict) -> list[TenderChange]:
    changes: list[TenderChange] = []
    for field in TRACKED_FIELDS:
        old = before.get(field)
        new = getattr(tender, field)
        old_s, new_s = _as_str(old), _as_str(new)
        if old_s == new_s:
            continue
        change = TenderChange(
            tender_id=tender.id,
            field=field,
            old_value=old_s,
            new_value=new_s,
            changed_at=datetime.now(timezone.utc),
        )
        db.add(change)
        changes.append(change)
    if changes:
        tender.changed_at = datetime.now(timezone.utc)
    return changes
