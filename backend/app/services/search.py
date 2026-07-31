from __future__ import annotations

import re

from sqlalchemy import not_, or_, text
from sqlalchemy.orm import Query

from app.database import is_postgres
from app.models import Tender

TOKEN_SPLIT_RE = re.compile(r"[\s,;]+")


def split_terms(value: str | None) -> list[str]:
    if not value:
        return []
    parts = TOKEN_SPLIT_RE.split(value.strip())
    return [p for p in parts if p]


def apply_fulltext(query: Query, q: str | None) -> Query:
    terms = split_terms(q)
    if not terms:
        return query

    if is_postgres():
        # Each include term must match (AND of plainto_tsquery).
        for i, term in enumerate(terms):
            param = f"q_inc_{i}"
            query = query.filter(
                text(f"tenders.search_vector @@ plainto_tsquery('russian', :{param})")
            ).params(**{param: term})
        return query

    # SQLite: every include term must appear in at least one searchable field.
    for term in terms:
        like = f"%{term}%"
        query = query.filter(
            or_(
                Tender.title.ilike(like),
                Tender.customer.ilike(like),
                Tender.description.ilike(like),
                Tender.external_id.ilike(like),
                Tender.okpd2.ilike(like),
                Tender.region.ilike(like),
                Tender.method.ilike(like),
            )
        )
    return query


def apply_exclusions(query: Query, exclude: str | None) -> Query:
    """Drop rows that contain ANY exclusion term in searchable fields."""
    terms = split_terms(exclude)
    if not terms:
        return query

    for i, term in enumerate(terms):
        like = f"%{term}%"
        # NOT (title OR customer OR description OR ...)
        hit = or_(
            Tender.title.ilike(like),
            Tender.customer.ilike(like),
            Tender.description.ilike(like),
            Tender.external_id.ilike(like),
            Tender.okpd2.ilike(like),
            Tender.region.ilike(like),
            Tender.method.ilike(like),
        )
        query = query.filter(not_(hit))

        if is_postgres():
            # Also exclude via FTS when vector is present.
            param = f"q_exc_{i}"
            query = query.filter(
                text(
                    f"(tenders.search_vector IS NULL OR NOT "
                    f"(tenders.search_vector @@ plainto_tsquery('russian', :{param})))"
                )
            ).params(**{param: term})
    return query


def fulltext_order_clause(q: str | None):
    terms = split_terms(q)
    if not terms or not is_postgres():
        return None
    # Rank by the full phrase for stable ordering.
    joined = " ".join(terms)
    return text("ts_rank(tenders.search_vector, plainto_tsquery('russian', :q_rank)) DESC").params(
        q_rank=joined
    )
