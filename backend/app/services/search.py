from __future__ import annotations

import re

from sqlalchemy import func, not_, or_, text
from sqlalchemy.orm import Query

from app.database import is_postgres
from app.models import Tender

# Prefer comma/semicolon so multi-word phrases stay intact.
# Fall back to whitespace when the user typed a simple space-separated query.
COMMA_SPLIT_RE = re.compile(r"[,;]+")
SPACE_SPLIT_RE = re.compile(r"\s+")

# Full niche OR queries exceed the old 40-term cap; keep a hard ceiling for safety.
MATCH_ANY_TERM_LIMIT = 80
RANK_TERM_LIMIT = 40

# OKPD-like codes first so they are never dropped when the query is long.
_OKPD_TERM_RE = re.compile(r"^\d{2}(?:\.\d{1,3}){0,4}$")


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


def prioritize_search_terms(terms: list[str], *, limit: int) -> list[str]:
    """Prefer OKPD codes, then longer phrases; preserve first-seen order within buckets."""
    if not terms:
        return []
    seen: set[str] = set()
    unique: list[str] = []
    for term in terms:
        key = term.casefold()
        if key in seen:
            continue
        seen.add(key)
        unique.append(term)
    if len(unique) <= limit:
        return unique
    okpd = [t for t in unique if _OKPD_TERM_RE.match(t)]
    rest = [t for t in unique if not _OKPD_TERM_RE.match(t)]
    # Longer phrases next (more specific), then shorter stems
    rest.sort(key=lambda t: (-len(t), unique.index(t)))
    ordered = okpd + rest
    return ordered[:limit]


def _field_hit(term: str):
    """True when any searchable field contains term.

    COALESCE is required so NULLs do not poison OR/NOT expressions:
    in SQL, `FALSE OR NULL` is NULL, and `NOT NULL` drops the row — which made
    any exclude filter return zero tenders.
    """
    like = f"%{term}%"
    return or_(
        func.coalesce(Tender.title, "").ilike(like),
        func.coalesce(Tender.customer, "").ilike(like),
        func.coalesce(Tender.description, "").ilike(like),
        func.coalesce(Tender.external_id, "").ilike(like),
        func.coalesce(Tender.okpd2, "").ilike(like),
        func.coalesce(Tender.region, "").ilike(like),
        func.coalesce(Tender.method, "").ilike(like),
    )


def apply_fulltext(query: Query, q: str | None, *, match_any: bool = False) -> Query:
    """Filter by search terms via ORM ILIKE (safe with later exclude filters)."""
    terms = split_terms(q)
    if not terms:
        return query

    if match_any:
        selected = prioritize_search_terms(terms, limit=MATCH_ANY_TERM_LIMIT)
        return query.filter(or_(*[_field_hit(term) for term in selected]))

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
        selected = prioritize_search_terms(terms, limit=RANK_TERM_LIMIT)
        for i, term in enumerate(selected):
            param = f"q_rank_{i}"
            parts.append(f"ts_rank(tenders.search_vector, plainto_tsquery('russian', :{param}))")
            binds[param] = term
        expr = " + ".join(parts) + " DESC"
        return text(expr).bindparams(**binds)

    joined = " ".join(terms)
    return text(
        "ts_rank(tenders.search_vector, plainto_tsquery('russian', :q_rank)) DESC"
    ).bindparams(q_rank=joined)
