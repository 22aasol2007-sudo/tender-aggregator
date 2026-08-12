"""5-minute supplier shortlist — no RFQ, no foreign prices."""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.orm import Session

from app.config import settings
from app.models import ClientSupplierBook, NicheSupplier, User
from app.services.contracts import top_suppliers_by_wins
from app.services.niches.registry import get_niche


def _norm_name(name: str) -> str:
    s = (name or "").casefold().strip()
    s = re.sub(r"[«»\"']", "", s)
    s = re.sub(r"\b(ооо|ао|зао|пао|ип)\b", "", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s[:512]


def _role_label(role: str | None) -> str:
    r = (role or "unknown").casefold()
    if r == "manufacturer":
        return "производитель"
    if r == "dealer":
        return "дилер / трейдер"
    return "роль неясна"


@dataclass
class ShortlistCandidate:
    name: str
    inn: str | None = None
    role: str = "unknown"
    city: str | None = None
    region: str | None = None
    website: str | None = None
    email: str | None = None
    phone: str | None = None
    fit_score: float = 0.0
    why: list[str] = field(default_factory=list)
    sources: list[str] = field(default_factory=list)
    # internal scoring helpers (stripped from API)
    _trust: float = 0.5
    _eis_wins: int = 0
    _web_confidence: float = 0.0
    _name_norm: str = ""

    def to_public(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "inn": self.inn,
            "role": self.role,
            "role_label": _role_label(self.role),
            "city": self.city,
            "region": self.region,
            "website": self.website,
            "email": self.email,
            "phone": self.phone,
            "fit_score": round(self.fit_score, 1),
            "why": self.why[:4],
            "sources": sorted(set(self.sources)),
        }


def _merge_into(
    bucket: dict[str, ShortlistCandidate],
    *,
    name: str,
    inn: str | None,
    role: str | None,
    city: str | None,
    region: str | None,
    website: str | None,
    email: str | None,
    phone: str | None,
    source: str,
    trust: float = 0.5,
    eis_wins: int = 0,
    web_confidence: float = 0.0,
    why_hint: str | None = None,
) -> None:
    nn = _norm_name(name)
    if not nn:
        return
    key = (inn or "").strip() or nn
    cur = bucket.get(key)
    if cur is None:
        # also try name match if inn key differs
        for k, c in list(bucket.items()):
            if c._name_norm == nn or (inn and c.inn == inn):
                cur = c
                key = k
                break
    if cur is None:
        cur = ShortlistCandidate(
            name=name.strip(),
            inn=(inn or None),
            role=(role or "unknown"),
            city=city,
            region=region,
            website=website,
            email=email,
            phone=phone,
            sources=[source],
            _trust=trust,
            _eis_wins=eis_wins,
            _web_confidence=web_confidence,
            _name_norm=nn,
        )
        if why_hint:
            cur.why.append(why_hint)
        bucket[key] = cur
        return

    if source not in cur.sources:
        cur.sources.append(source)
    if inn and not cur.inn:
        cur.inn = inn
    if role and cur.role in ("unknown", "", None):
        cur.role = role
    elif role == "manufacturer":
        cur.role = "manufacturer"
    if city and not cur.city:
        cur.city = city
    if region and not cur.region:
        cur.region = region
    if website and not cur.website:
        cur.website = website
    if email and not cur.email:
        cur.email = email
    if phone and not cur.phone:
        cur.phone = phone
    cur._trust = max(cur._trust, trust)
    cur._eis_wins = max(cur._eis_wins, eis_wins)
    cur._web_confidence = max(cur._web_confidence, web_confidence)
    if why_hint and why_hint not in cur.why:
        cur.why.append(why_hint)


def _from_client_book(db: Session, user: User | None, bucket: dict[str, ShortlistCandidate]) -> None:
    if user is None:
        return
    rows = (
        db.query(ClientSupplierBook)
        .filter(ClientSupplierBook.user_id == user.id)
        .order_by(ClientSupplierBook.updated_at.desc())
        .limit(40)
        .all()
    )
    for b in rows:
        contacts = b.contacts or {}
        _merge_into(
            bucket,
            name=b.name,
            inn=b.supplier_inn,
            role="unknown",
            city=None,
            region=None,
            website=contacts.get("website") or contacts.get("url"),
            email=contacts.get("email"),
            phone=contacts.get("phone"),
            source="client_book",
            trust=0.85,
            why_hint="Есть в вашей книге поставщиков",
        )


def _from_niche_seed(
    db: Session,
    *,
    niche_id: str,
    product: str,
    city: str,
    bucket: dict[str, ShortlistCandidate],
) -> None:
    rows = (
        db.query(NicheSupplier)
        .filter(NicheSupplier.niche_id == niche_id, NicheSupplier.active.is_(True))
        .order_by(NicheSupplier.trust_seed.desc())
        .limit(80)
        .all()
    )
    prod = product.casefold()
    city_l = city.casefold()
    for r in rows:
        tags = " ".join(str(t) for t in (r.tags or [])).casefold()
        blob = f"{r.name} {tags} {r.notes or ''}".casefold()
        # Prefer seed rows that look related; still keep strong manufacturers
        related = any(tok in blob for tok in ("гофр", "картон", "короб", "упаков", "gofra")) or True
        if not related:
            continue
        why = "В кураторской базе ниши"
        if r.role == "manufacturer":
            why = "Производитель из кураторской базы ниши"
        if city_l and r.city and city_l[:4] in (r.city or "").casefold():
            why += f" · поставки в {r.city}"
        # mild boost if product tokens hit tags
        trust = float(r.trust_seed or 0.7)
        if any(w in tags or w in blob for w in prod.split() if len(w) > 3):
            trust = min(1.0, trust + 0.05)
        _merge_into(
            bucket,
            name=r.name,
            inn=r.inn,
            role=r.role,
            city=r.city,
            region=r.region,
            website=r.website,
            email=r.email,
            phone=r.phone,
            source="niche_seed",
            trust=trust,
            why_hint=why,
        )


def _from_eis(
    db: Session,
    *,
    search_terms: list[str],
    city: str,
    bucket: dict[str, ShortlistCandidate],
) -> None:
    # One combined query string works better than many tiny queries on sparse DB
    q = " ".join(search_terms[:4]) if search_terms else "гофрокартон"
    region = city if city else None
    try:
        rows = top_suppliers_by_wins(db, q=q, region=region, limit=20)
        if len(rows) < 5 and region:
            rows = top_suppliers_by_wins(db, q=q, region=None, limit=20)
    except Exception:  # noqa: BLE001
        rows = []
    for row in rows:
        wins = int(row.get("wins") or 0)
        name = row.get("supplier_name") or ""
        if not name:
            continue
        why = f"Победитель в контрактах по упаковке/гофре ({wins} шт.)"
        _merge_into(
            bucket,
            name=name,
            inn=row.get("supplier_inn"),
            role="unknown",
            city=city or None,
            region=None,
            website=None,
            email=None,
            phone=None,
            source="eis_contracts",
            trust=min(0.9, 0.55 + 0.03 * min(wins, 10)),
            eis_wins=wins,
            why_hint=why,
        )


def _score_candidate(
    c: ShortlistCandidate,
    *,
    city: str,
    search_terms: list[str],
) -> None:
    score = 35.0
    why = list(c.why)

    # Role
    if c.role == "manufacturer":
        score += 18
        why.append("Производитель — приоритетнее перекупа")
    elif c.role == "dealer":
        score += 8

    # Region / city
    city_l = (city or "").casefold()
    loc = f"{c.city or ''} {c.region or ''}".casefold()
    if city_l and city_l[:4] in loc:
        score += 14
        why.append(f"Ориентир на регион: {city}")
    elif "моск" in loc or "москов" in loc:
        score += 10

    # Contacts
    if c.email or c.phone:
        score += 10
        why.append("Есть контакт для связи")
    if c.website:
        score += 6

    # Trust / sources
    score += 20 * float(c._trust or 0.5)
    if "client_book" in c.sources:
        score += 12
    if "niche_seed" in c.sources:
        score += 8
    if "eis_contracts" in c.sources:
        score += min(15, 4 + c._eis_wins)
    if "web_research" in c.sources:
        score += 6 * float(c._web_confidence or 0.4)
        if (c._web_confidence or 0) < 0.45:
            score -= 8
            why.append("Кандидат из веб-исследования — проверить вручную")

    # Term overlap in name
    blob = c.name.casefold()
    hits = sum(1 for t in search_terms if t[:5].casefold() in blob)
    if hits:
        score += min(8, hits * 2)

    c.fit_score = max(0.0, min(100.0, score))
    # Keep unique why, prefer shortest set
    seen: set[str] = set()
    uniq: list[str] = []
    for w in why:
        if w not in seen:
            seen.add(w)
            uniq.append(w)
    c.why = uniq[:4]


def build_shortlist(
    db: Session,
    *,
    user: User | None = None,
    niche_id: str | None = None,
    product: str,
    city: str | None = None,
    qty: float | None = None,
    unit: str | None = None,
    attrs: dict | None = None,
    limit: int | None = None,
    include_web: bool = True,
) -> dict[str, Any]:
    """Build ranked supplier shortlist without RFQ or prices."""
    t0 = time.perf_counter()
    niche = get_niche(niche_id)
    city_s = (city or niche.default_city or "Москва").strip()
    attrs_n = niche.normalize_attrs(attrs)
    lim = limit or int(getattr(settings, "shortlist_limit_default", 12))
    lim = max(3, min(25, lim))

    bucket: dict[str, ShortlistCandidate] = {}
    _from_client_book(db, user, bucket)
    _from_niche_seed(db, niche_id=niche.id, product=product, city=city_s, bucket=bucket)
    _from_eis(db, search_terms=list(niche.search_terms), city=city_s, bucket=bucket)

    web_error: str | None = None
    web_count = 0
    if include_web and getattr(settings, "openai_api_key", None):
        try:
            from app.services.web_supplier_research import research_suppliers_web

            web_rows = research_suppliers_web(
                product=product,
                city=city_s,
                qty=qty,
                unit=unit,
                attrs=attrs_n,
                niche_title=niche.title,
                search_terms=list(niche.search_terms),
            )
            web_count = len(web_rows)
            for w in web_rows:
                _merge_into(
                    bucket,
                    name=w.get("name") or "",
                    inn=w.get("inn"),
                    role=w.get("role") or "unknown",
                    city=w.get("city") or city_s,
                    region=w.get("region"),
                    website=w.get("website"),
                    email=w.get("email"),
                    phone=w.get("phone"),
                    source="web_research",
                    trust=0.45 + 0.4 * float(w.get("confidence") or 0.4),
                    web_confidence=float(w.get("confidence") or 0.4),
                    why_hint=(w.get("reasons") or ["Найден при исследовании рынка"])[0]
                    if isinstance(w.get("reasons"), list)
                    else "Найден при исследовании рынка",
                )
                reasons = w.get("reasons") if isinstance(w.get("reasons"), list) else []
                key = (w.get("inn") or "").strip() or _norm_name(w.get("name") or "")
                cand = bucket.get(key)
                if cand:
                    for r in reasons[:2]:
                        if r and r not in cand.why:
                            cand.why.append(str(r))
        except Exception as exc:  # noqa: BLE001
            web_error = str(exc)[:240]

    for c in bucket.values():
        _score_candidate(c, city=city_s, search_terms=list(niche.search_terms))

    ranked = sorted(bucket.values(), key=lambda x: x.fit_score, reverse=True)[:lim]
    took_ms = int((time.perf_counter() - t0) * 1000)
    return {
        "took_ms": took_ms,
        "niche_id": niche.id,
        "niche_title": niche.title,
        "product": product.strip(),
        "city": city_s,
        "qty": qty,
        "unit": unit,
        "attrs": attrs_n,
        "disclaimer": "Кандидаты по рынку и сигналам · цены только после ответа поставщика · это не КП",
        "sources_used": sorted(
            {s for c in ranked for s in c.sources}
            | ({"web_research"} if web_count else set())
        ),
        "web_research": {"attempted": include_web, "count": web_count, "error": web_error},
        "candidates": [c.to_public() for c in ranked],
    }
