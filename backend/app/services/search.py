from __future__ import annotations

import itertools
import re

from sqlalchemy import and_, bindparam, func, not_, or_, text
from sqlalchemy.orm import Query

from app.database import is_postgres
from app.models import Tender

# Prefer comma/semicolon so multi-word phrases stay intact.
# Fall back to whitespace when the user typed a simple space-separated query.
COMMA_SPLIT_RE = re.compile(r"[,;]+")
SPACE_SPLIT_RE = re.compile(r"\s+")

# Full niche OR queries exceed the old 40-term cap; keep a hard ceiling for safety.
# TRANSPORT_INCLUDE_TERMS ≈ 62 — leave headroom for user extras.
MATCH_ANY_TERM_LIMIT = 80
RANK_TERM_LIMIT = 40

# OKPD-like codes — match okpd2 prefix only (avoid price/false hits like 49.4 in amounts).
_OKPD_TERM_RE = re.compile(r"^\d{2}(?:\.\d{1,3}){0,4}$")

_bind_seq = itertools.count(1)


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
    rest.sort(key=lambda t: (-len(t), unique.index(t)))
    return (okpd + rest)[:limit]


def _like_param(term: str, *, prefix: str = "ft_like"):
    """Fresh bindparam per use — reusing one bind across OR/AND nests collapses Postgres matches."""
    n = next(_bind_seq)
    return bindparam(f"{prefix}_{n}", f"%{term}%")


def _field_hit(term: str, *, null_safe: bool = False):
    """True when any searchable field contains term."""
    if not null_safe:
        return or_(
            Tender.title.ilike(_like_param(term)),
            Tender.customer.ilike(_like_param(term)),
            Tender.description.ilike(_like_param(term)),
            Tender.external_id.ilike(_like_param(term)),
            Tender.okpd2.ilike(_like_param(term)),
            Tender.region.ilike(_like_param(term)),
            Tender.method.ilike(_like_param(term)),
        )
    n = next(_bind_seq)
    empty = bindparam(f"ft_empty_{n}", "")
    return or_(
        func.coalesce(Tender.title, empty).ilike(_like_param(term)),
        func.coalesce(Tender.customer, empty).ilike(_like_param(term)),
        func.coalesce(Tender.description, empty).ilike(_like_param(term)),
        func.coalesce(Tender.external_id, empty).ilike(_like_param(term)),
        func.coalesce(Tender.okpd2, empty).ilike(_like_param(term)),
        func.coalesce(Tender.region, empty).ilike(_like_param(term)),
        func.coalesce(Tender.method, empty).ilike(_like_param(term)),
    )


def _okpd_hit(code: str):
    """OKPD codes match okpd2 prefix only — never free-text (prices/dates)."""
    n = next(_bind_seq)
    return Tender.okpd2.ilike(bindparam(f"ft_okpd_{n}", f"{code}%"))


def _phrase_hit(phrase: str, *, null_safe: bool = False):
    """One niche alternative: OKPD code, single stem, or AND of words in a phrase."""
    if _OKPD_TERM_RE.match(phrase):
        return _okpd_hit(phrase)
    words = [w for w in SPACE_SPLIT_RE.split(phrase) if w]
    if not words:
        return _field_hit(phrase, null_safe=null_safe)
    if len(words) == 1:
        return _field_hit(words[0], null_safe=null_safe)
    # Multi-word phrase: all words must appear (possibly in different fields).
    # Each word gets its own field OR; unique binds keep nested OR(AND(...)) correct on PG.
    return and_(*[_field_hit(w, null_safe=null_safe) for w in words])


def apply_fulltext(query: Query, q: str | None, *, match_any: bool = False) -> Query:
    """Filter by search terms via ORM ILIKE (safe with later exclude filters)."""
    terms = split_terms(q)
    if not terms:
        return query

    if match_any:
        selected = prioritize_search_terms(terms, limit=MATCH_ANY_TERM_LIMIT)
        if not selected:
            return query
        if len(selected) == 1:
            return query.filter(_phrase_hit(selected[0], null_safe=False))
        return query.filter(or_(*[_phrase_hit(term, null_safe=False) for term in selected]))

    for term in terms:
        query = query.filter(_phrase_hit(term, null_safe=False))
    return query


def apply_exclusions(query: Query, exclude: str | None) -> Query:
    """Drop rows that contain ANY exclusion term in searchable fields."""
    terms = split_terms(exclude)
    if not terms:
        return query

    for term in terms:
        # Exclusions stay null-safe; multi-word exclude = AND (all words present)
        query = query.filter(not_(_phrase_hit(term, null_safe=True)))
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
