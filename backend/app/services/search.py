from __future__ import annotations

import re

from sqlalchemy import not_, or_, text
from sqlalchemy.orm import Query

from app.database import is_postgres
from app.models import Tender

# Prefer comma/semicolon so multi-word phrases stay intact.
# Fall back to whitespace when the user typed a simple space-separated query.
COMMA_SPLIT_RE = re.compile(r"[,;]+")
SPACE_SPLIT_RE = re.compile(r"\s+")


def split_terms(value: str | None) -> list[str]:
    if not value:
        return []
    raw = value.strip()
    if not raw:
        return []
    if "," in raw or ";" in raw:
        parts = COMMA_SPLIT_RE.split(raw)
    else:
        parts = SPACE_SPLIT_RE.split(raw)
    return [p.strip() for p in parts if p.strip()]


def _field_hit(term: str):
    like = f"%{term}%"
    return or_(
        Tender.title.ilike(like),
        Tender.customer.ilike(like),
        Tender.description.ilike(like),
        Tender.external_id.ilike(like),
        Tender.okpd2.ilike(like),
        Tender.region.ilike(like),
        Tender.method.ilike(like),
    )


def apply_fulltext(query: Query, q: str | None, *, match_any: bool = False) -> Query:
    """Filter by search terms.

    Uses ORM ILIKE (not raw text().params) so later filters like exclusions
    cannot drop bind parameters and silently zero out results.
    """
    terms = split_terms(q)
    if not terms:
        return query

    # Cap OR fan-out for huge niche defaults
    if match_any:
        return query.filter(or_(*[_field_hit(term) for term in terms[:40]]))

    for term in terms:
        query = query.filter(_field_hit(term))
    return query


def apply_exclusions(query: Query, exclude: str | None) -> Query:
    """Drop rows that contain ANY exclusion term in searchable fields."""
    terms = split_terms(exclude)
    if not terms:
        return query

    for term in terms:
        query = query.filter(not_(_field_hit(term)))
    return query


def fulltext_order_clause(q: str | None, *, match_any: bool = False):
    """Optional Postgres relevance ORDER BY (bindparams stay on the clause)."""
    terms = split_terms(q)
    if not terms or not is_postgres():
        return None
    if match_any:
        parts = []
        binds: dict[str, str] = {}
        for i, term in enumerate(terms[:20]):
            param = f"q_rank_{i}"
            parts.append(f"ts_rank(tenders.search_vector, plainto_tsquery('russian', :{param}))")
            binds[param] = term
        expr = " + ".join(parts) + " DESC"
        return text(expr).bindparams(**binds)

    joined = " ".join(terms)
    return text(
        "ts_rank(tenders.search_vector, plainto_tsquery('russian', :q_rank)) DESC"
    ).bindparams(q_rank=joined)
