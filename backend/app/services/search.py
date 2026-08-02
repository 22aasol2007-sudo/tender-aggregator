from __future__ import annotations

import itertools
import re

from sqlalchemy import bindparam, false, func, not_, or_, text
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

_SEARCH_COLS = (
    "title",
    "customer",
    "description",
    "external_id",
    "okpd2",
    "region",
    "method",
)


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


def _field_hit(term: str, *, null_safe: bool = False):
    """True when any searchable field contains term (ORM path for single-term / AND)."""
    pattern = f"%{term}%"
    if not null_safe:
        return or_(
            Tender.title.ilike(pattern),
            Tender.customer.ilike(pattern),
            Tender.description.ilike(pattern),
            Tender.external_id.ilike(pattern),
            Tender.okpd2.ilike(pattern),
            Tender.region.ilike(pattern),
            Tender.method.ilike(pattern),
        )
    n = next(_bind_seq)
    empty = bindparam(f"ft_empty_{n}", "")
    return or_(
        func.coalesce(Tender.title, empty).ilike(pattern),
        func.coalesce(Tender.customer, empty).ilike(pattern),
        func.coalesce(Tender.description, empty).ilike(pattern),
        func.coalesce(Tender.external_id, empty).ilike(pattern),
        func.coalesce(Tender.okpd2, empty).ilike(pattern),
        func.coalesce(Tender.region, empty).ilike(pattern),
        func.coalesce(Tender.method, empty).ilike(pattern),
    )


def _okpd_hit(code: str):
    """OKPD codes match okpd2 prefix only — never free-text (prices/dates)."""
    return Tender.okpd2.ilike(f"{code}%")


def _phrase_hit(phrase: str, *, null_safe: bool = False):
    """One niche alternative: OKPD code, single stem, or multi-word glued ILIKE."""
    if _OKPD_TERM_RE.match(phrase):
        return _okpd_hit(phrase)
    words = [w for w in SPACE_SPLIT_RE.split(phrase) if w]
    if not words:
        return _field_hit(phrase, null_safe=null_safe)
    if len(words) == 1:
        return _field_hit(words[0], null_safe=null_safe)
    # Glued pattern in any field (%w1%w2%) — avoids and_() which breaks match_any OR.
    return _field_hit("%".join(words), null_safe=null_safe)


def _ids_for_term(session, term: str) -> set[int]:
    """Fetch matching ids with raw SQL (avoids ORM multi-clause bind/cache bugs).

    Must mirror _phrase_hit: OKPD prefix, single-stem ILIKE, or glued multi-word
    (%w1%w2%) in any searchable field. concat_ws AND-of-words was returning ~0
    on live Postgres while the glued ORM path matched dozens of rows.
    """
    n = next(_bind_seq)
    if _OKPD_TERM_RE.match(term):
        key = f"okpd_{n}"
        sql = text(f"SELECT id FROM tenders WHERE okpd2 ILIKE :{key}")
        rows = session.execute(sql, {key: f"{term}%"}).fetchall()
        return {int(r[0]) for r in rows}

    words = [w for w in SPACE_SPLIT_RE.split(term) if w]
    if not words:
        return set()

    # Single stem or glued multi-word — same pattern shape as _phrase_hit/_field_hit.
    needle = words[0] if len(words) == 1 else "%".join(words)
    pattern = f"%{needle}%"
    params = {f"p{n}_{i}": pattern for i in range(len(_SEARCH_COLS))}
    ors = " OR ".join(f"{col} ILIKE :p{n}_{i}" for i, col in enumerate(_SEARCH_COLS))
    sql = text(f"SELECT id FROM tenders WHERE {ors}")
    rows = session.execute(sql, params).fetchall()
    return {int(r[0]) for r in rows}


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
        # Multi-term: raw SQL per term, merge ids. ORM or_/UNION of complex ILIKE
        # trees collapses phrase branches on Postgres.
        matched: set[int] = set()
        session = query.session
        for term in selected:
            matched |= _ids_for_term(session, term)
        if not matched:
            return query.filter(false())
        return query.filter(Tender.id.in_(matched))

    for term in terms:
        query = query.filter(_phrase_hit(term, null_safe=False))
    return query


def apply_exclusions(query: Query, exclude: str | None) -> Query:
    """Drop rows that contain ANY exclusion term in searchable fields."""
    terms = split_terms(exclude)
    if not terms:
        return query

    for term in terms:
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
