from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.orm import Query, Session

from app.config import settings
from app.models import Tender
from app.services.search import apply_exclusions, apply_fulltext


def apply_tender_filters(
    query: Query,
    *,
    q: str | None = None,
    exclude: str | None = None,
    match_any: bool = False,
    source: str | None = None,
    law: str | None = None,
    region: str | None = None,
    method: str | None = None,
    okpd2: str | None = None,
    status_norm: str | None = None,
    min_price: float | None = None,
    max_price: float | None = None,
    deadline_from: datetime | None = None,
    deadline_to: datetime | None = None,
    hide_outdated: bool | None = None,
    hide_duplicates: bool = True,
) -> Query:
    if hide_outdated is None:
        hide_outdated = settings.hide_outdated_default

    query = apply_fulltext(query, q, match_any=match_any)
    query = apply_exclusions(query, exclude)
    if source:
        query = query.filter(Tender.source == source)
    if law:
        query = query.filter(Tender.law == law)
    if region:
        query = query.filter(Tender.region.ilike(f"%{region.strip()}%"))
    if method:
        query = query.filter(Tender.method.ilike(f"%{method.strip()}%"))
    if okpd2:
        query = query.filter(Tender.okpd2.ilike(f"{okpd2.strip()}%"))
    if status_norm:
        query = query.filter(Tender.status_norm == status_norm)
    if min_price is not None:
        query = query.filter(Tender.price >= min_price)
    if max_price is not None:
        query = query.filter(Tender.price <= max_price)
    if deadline_from is not None:
        query = query.filter(Tender.deadline_at >= deadline_from)
    if deadline_to is not None:
        query = query.filter(Tender.deadline_at <= deadline_to)
    if hide_duplicates:
        query = query.filter(Tender.is_duplicate.is_(False))
    if hide_outdated:
        now = datetime.now(timezone.utc)
        query = query.filter((Tender.deadline_at.is_(None)) | (Tender.deadline_at >= now))
        if not status_norm:
            query = query.filter(Tender.status_norm == "accepting")
        else:
            query = query.filter(Tender.status_norm != "cancelled")
    return query


def filters_from_dict(raw: dict) -> dict:
    def fnum(key: str):
        val = raw.get(key)
        if val in (None, ""):
            return None
        return float(val)

    def fstr(key: str):
        val = raw.get(key)
        return str(val) if val not in (None, "") else None

    def fbool(key: str, default: bool):
        if key not in raw:
            return default
        val = raw[key]
        if isinstance(val, str):
            return val.strip().lower() in {"1", "true", "yes", "on"}
        return bool(val)

    def fdt(key: str):
        val = raw.get(key)
        if val in (None, ""):
            return None
        if isinstance(val, datetime):
            return val
        try:
            return datetime.fromisoformat(str(val).replace("Z", "+00:00"))
        except ValueError:
            return None

    return {
        "q": fstr("q"),
        "exclude": fstr("exclude"),
        "match_any": fbool("match_any", True),
        "source": fstr("source"),
        "law": fstr("law"),
        "region": fstr("region"),
        "method": fstr("method"),
        "okpd2": fstr("okpd2"),
        "status_norm": fstr("status_norm"),
        "min_price": fnum("min_price"),
        "max_price": fnum("max_price"),
        "deadline_from": fdt("deadline_from"),
        "deadline_to": fdt("deadline_to"),
        "hide_outdated": fbool("hide_outdated", True),
        "hide_duplicates": fbool("hide_duplicates", True),
    }


def query_from_filters(db: Session, raw: dict) -> Query:
    params = filters_from_dict(raw)
    return apply_tender_filters(db.query(Tender), **params)
