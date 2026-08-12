from __future__ import annotations

import hashlib
import re
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.config import settings
from app.models import ClientSupplierBook, Contract, MarketOfferObservation, MarketQueryCache
from app.services.normalize import normalize_region, normalize_text

# Stopwords that should not dominate fingerprints
_STOP = {
    "поставка",
    "поставки",
    "закупка",
    "нужно",
    "нужен",
    "нужна",
    "ищу",
    "лучший",
    "поставщик",
    "поставщика",
    "цена",
    "стоимость",
    "для",
    "или",
    "and",
    "the",
}

_CITY_ALIASES = {
    "мск": "москва",
    "moscow": "москва",
    "спб": "санкт-петербург",
    "питер": "санкт-петербург",
    "петербург": "санкт-петербург",
}


def qty_band(qty: float | None) -> str:
    if qty is None or qty <= 0:
        return "unknown"
    if qty < 10:
        return "1-10"
    if qty < 100:
        return "10-100"
    if qty < 1000:
        return "100-1000"
    if qty < 10000:
        return "1k-10k"
    return "10k+"


def _tokens(text: str) -> list[str]:
    words = re.findall(r"[a-zA-Zа-яА-ЯёЁ0-9\.]{2,}", (text or "").casefold())
    out: list[str] = []
    for w in words:
        if w in _STOP:
            continue
        out.append(w)
    return sorted(set(out))[:24]


def normalize_city(city: str | None) -> str:
    raw = normalize_region(city) or normalize_text(city) or (city or "")
    key = raw.casefold().strip()
    key = _CITY_ALIASES.get(key, key)
    return key[:128]


def build_fingerprint(
    *,
    product: str,
    city: str | None = None,
    qty: float | None = None,
    unit: str | None = None,
) -> dict[str, str]:
    category_key = " ".join(_tokens(product)) or "unknown"
    city_key = normalize_city(city)
    band = qty_band(qty)
    unit_key = (unit or "").casefold().strip()[:32]
    material = f"{category_key}|{city_key}|{band}|{unit_key}"
    fingerprint = hashlib.sha256(material.encode("utf-8")).hexdigest()[:40]
    return {
        "fingerprint": fingerprint,
        "category_key": category_key[:128],
        "city_key": city_key,
        "qty_band": band,
        "unit": unit_key or None,
    }


def _ttl_days() -> int:
    return max(1, int(getattr(settings, "market_cache_ttl_days", 14)))


def _expires_at(from_dt: datetime | None = None) -> datetime:
    base = from_dt or datetime.now(timezone.utc)
    return base + timedelta(days=_ttl_days())


def _sanitize_payload(payload: dict | None) -> dict:
    """Strip secrets / PII before cross-client reuse."""
    if not payload:
        return {}
    banned = {
        "email",
        "emails",
        "phone",
        "phones",
        "client",
        "client_name",
        "company",
        "contact",
        "contacts",
        "manager",
        "raw_pdf",
        "raw_text",
        "message_id",
    }
    clean: dict[str, Any] = {}
    for k, v in payload.items():
        if k.casefold() in banned:
            continue
        if isinstance(v, str) and ("@" in v or re.search(r"\+?\d[\d\-\s]{8,}\d", v)):
            continue
        clean[k] = v
    return clean


def lookup_market_cache(
    db: Session,
    *,
    product: str,
    city: str | None = None,
    qty: float | None = None,
    unit: str | None = None,
    allow_stale: bool = False,
) -> dict[str, Any]:
    meta = build_fingerprint(product=product, city=city, qty=qty, unit=unit)
    now = datetime.now(timezone.utc)
    row = db.query(MarketQueryCache).filter(MarketQueryCache.fingerprint == meta["fingerprint"]).first()

    if row is None:
        # Soft match: same category+city, ignore qty band if exact miss
        soft = (
            db.query(MarketQueryCache)
            .filter(
                MarketQueryCache.category_key == meta["category_key"],
                MarketQueryCache.city_key == meta["city_key"],
            )
            .order_by(MarketQueryCache.updated_at.desc())
            .first()
        )
        if soft is None:
            return {
                "hit": False,
                "reason": "miss",
                "fingerprint": meta["fingerprint"],
                "meta": meta,
                "offers": [],
                "summary": None,
            }
        row = soft
        match_type = "soft"
    else:
        match_type = "exact"

    expired = row.expires_at.replace(tzinfo=timezone.utc) if row.expires_at.tzinfo is None else row.expires_at
    if expired < now and not allow_stale:
        return {
            "hit": False,
            "reason": "expired",
            "fingerprint": row.fingerprint,
            "meta": meta,
            "match_type": match_type,
            "offers": [],
            "summary": row.result_summary,
            "expires_at": row.expires_at,
        }

    offers = (
        db.query(MarketOfferObservation)
        .filter(
            or_(
                MarketOfferObservation.query_cache_id == row.id,
                MarketOfferObservation.fingerprint == row.fingerprint,
            )
        )
        .order_by(MarketOfferObservation.landed_unit_price.asc().nullslast(), MarketOfferObservation.id.desc())
        .limit(30)
        .all()
    )

    # Estimate token savings: deep search avoided
    saved = int(getattr(settings, "market_cache_tokens_saved_per_hit", 120_000))
    row.hit_count = int(row.hit_count or 0) + 1
    row.token_saved_estimate = int(row.token_saved_estimate or 0) + saved
    db.commit()

    return {
        "hit": True,
        "reason": "hit",
        "match_type": match_type,
        "fingerprint": row.fingerprint,
        "meta": {
            "category_key": row.category_key,
            "city_key": row.city_key,
            "qty_band": row.qty_band,
            "unit": row.unit,
        },
        "summary": row.result_summary or {},
        "offer_count": row.offer_count,
        "hit_count": row.hit_count,
        "token_saved_estimate": row.token_saved_estimate,
        "expires_at": row.expires_at,
        "updated_at": row.updated_at,
        "offers": [_offer_dict(o) for o in offers],
        "tokens_saved_this_hit": saved,
    }


def _offer_dict(o: MarketOfferObservation) -> dict[str, Any]:
    return {
        "id": o.id,
        "source_type": o.source_type,
        "supplier_name": o.supplier_name,
        "supplier_inn": o.supplier_inn,
        "city_from": o.city_from,
        "city_to": o.city_to,
        "unit": o.unit,
        "qty": o.qty,
        "price_value": o.price_value,
        "currency": o.currency,
        "vat": o.vat,
        "delivery_price": o.delivery_price,
        "landed_unit_price": o.landed_unit_price,
        "lead_time_days": o.lead_time_days,
        "payment_terms": o.payment_terms,
        "confidence": o.confidence,
        "observed_at": o.observed_at,
        "expires_at": o.expires_at,
        "payload": o.payload or {},
    }


def save_market_result(
    db: Session,
    *,
    product: str,
    city: str | None = None,
    qty: float | None = None,
    unit: str | None = None,
    offers: list[dict[str, Any]] | None = None,
    summary: dict[str, Any] | None = None,
    query_raw: str | None = None,
) -> dict[str, Any]:
    meta = build_fingerprint(product=product, city=city, qty=qty, unit=unit)
    now = datetime.now(timezone.utc)
    row = db.query(MarketQueryCache).filter(MarketQueryCache.fingerprint == meta["fingerprint"]).first()
    if row is None:
        row = MarketQueryCache(
            fingerprint=meta["fingerprint"],
            category_key=meta["category_key"],
            city_key=meta["city_key"],
            qty_band=meta["qty_band"],
            unit=meta["unit"],
            query_raw=(query_raw or product)[:2000],
            result_summary=summary or {},
            offer_count=0,
            expires_at=_expires_at(now),
        )
        db.add(row)
        db.flush()
    else:
        row.category_key = meta["category_key"]
        row.city_key = meta["city_key"]
        row.qty_band = meta["qty_band"]
        row.unit = meta["unit"]
        if summary:
            row.result_summary = summary
        if query_raw:
            row.query_raw = query_raw[:2000]
        row.expires_at = _expires_at(now)

    source_mix: dict[str, int] = dict(row.source_mix or {})
    saved_offers = 0
    for raw in offers or []:
        source_type = str(raw.get("source_type") or "rfq")[:32]
        obs = MarketOfferObservation(
            fingerprint=meta["fingerprint"],
            query_cache_id=row.id,
            source_type=source_type,
            supplier_name=(raw.get("supplier_name") or None),
            supplier_inn=(raw.get("supplier_inn") or None),
            city_from=raw.get("city_from"),
            city_to=raw.get("city_to") or meta["city_key"] or None,
            unit=raw.get("unit") or unit,
            qty=raw.get("qty") if raw.get("qty") is not None else qty,
            price_value=raw.get("price_value"),
            currency=raw.get("currency") or "RUB",
            vat=raw.get("vat"),
            delivery_price=raw.get("delivery_price"),
            landed_unit_price=raw.get("landed_unit_price"),
            lead_time_days=raw.get("lead_time_days"),
            payment_terms=raw.get("payment_terms"),
            confidence=float(raw.get("confidence") or 0.7),
            payload=_sanitize_payload(raw.get("payload") if isinstance(raw.get("payload"), dict) else raw),
            observed_at=now,
            expires_at=_expires_at(now),
        )
        db.add(obs)
        saved_offers += 1
        source_mix[source_type] = int(source_mix.get(source_type, 0)) + 1

    row.offer_count = int(row.offer_count or 0) + saved_offers
    row.source_mix = source_mix
    db.commit()
    db.refresh(row)
    return {
        "saved": True,
        "fingerprint": row.fingerprint,
        "query_cache_id": row.id,
        "offers_saved": saved_offers,
        "offer_count": row.offer_count,
        "expires_at": row.expires_at,
    }


def ingest_contracts_into_cache(
    db: Session,
    *,
    q: str | None = None,
    region: str | None = None,
    limit: int = 200,
) -> dict[str, Any]:
    """Bootstrap shared cache from EIS contract winners (no LLM tokens)."""
    from app.services.contracts import apply_contract_filters

    query = apply_contract_filters(db.query(Contract), q=q, region=region)
    rows = (
        query.filter(Contract.price.isnot(None))
        .order_by(Contract.signed_at.desc().nullslast())
        .limit(limit)
        .all()
    )
    grouped: dict[str, list[Contract]] = {}
    for c in rows:
        product = c.title or ""
        city = c.region or region or ""
        meta = build_fingerprint(product=product, city=city, qty=None, unit=None)
        grouped.setdefault(meta["fingerprint"], []).append(c)

    queries_touched = 0
    offers_saved = 0
    for _fp, contracts in grouped.items():
        sample = contracts[0]
        offers = []
        for c in contracts[:15]:
            offers.append(
                {
                    "source_type": "contract",
                    "supplier_name": c.supplier_name,
                    "supplier_inn": c.supplier_inn,
                    "city_to": c.region,
                    "price_value": c.price,
                    "landed_unit_price": c.price,
                    "confidence": 0.85,
                    "payload": {
                        "okpd2": c.okpd2,
                        "nmck": c.nmck,
                        "discount_pct": c.discount_pct,
                        "contract_external_id": c.external_id,
                        "law": c.law,
                    },
                }
            )
        prices = [c.price for c in contracts if c.price is not None]
        summary = {
            "from_contracts": True,
            "count": len(contracts),
            "median_price": sorted(prices)[len(prices) // 2] if prices else None,
            "top_supplier": sample.supplier_name,
        }
        res = save_market_result(
            db,
            product=sample.title,
            city=sample.region,
            offers=offers,
            summary=summary,
            query_raw=sample.title,
        )
        queries_touched += 1
        offers_saved += int(res.get("offers_saved") or 0)

    return {"queries_touched": queries_touched, "offers_saved": offers_saved, "contracts_read": len(rows)}


def upsert_client_supplier(
    db: Session,
    *,
    user_id: int,
    name: str,
    supplier_inn: str | None = None,
    contacts: dict | None = None,
    notes: str | None = None,
    tags: list | None = None,
) -> ClientSupplierBook:
    name_clean = normalize_text(name) or name.strip()
    name_norm = name_clean.casefold()[:512]
    inn = (supplier_inn or "").strip() or None
    row = None
    if inn:
        row = (
            db.query(ClientSupplierBook)
            .filter(ClientSupplierBook.user_id == user_id, ClientSupplierBook.supplier_inn == inn)
            .first()
        )
    if row is None:
        row = (
            db.query(ClientSupplierBook)
            .filter(ClientSupplierBook.user_id == user_id, ClientSupplierBook.name_normalized == name_norm)
            .first()
        )
    if row is None:
        row = ClientSupplierBook(
            user_id=user_id,
            name=name_clean,
            name_normalized=name_norm,
            supplier_inn=inn,
            contacts=contacts or {},
            notes=notes,
            tags=tags or [],
        )
        db.add(row)
    else:
        row.name = name_clean
        row.name_normalized = name_norm
        if inn:
            row.supplier_inn = inn
        if contacts is not None:
            row.contacts = contacts
        if notes is not None:
            row.notes = notes
        if tags is not None:
            row.tags = tags
    db.commit()
    db.refresh(row)
    return row


def list_client_suppliers(db: Session, user_id: int, q: str | None = None, limit: int = 100) -> list[ClientSupplierBook]:
    query = db.query(ClientSupplierBook).filter(ClientSupplierBook.user_id == user_id)
    if q:
        like = f"%{q.strip()}%"
        query = query.filter(
            or_(ClientSupplierBook.name.ilike(like), ClientSupplierBook.supplier_inn.ilike(like))
        )
    return query.order_by(ClientSupplierBook.updated_at.desc()).limit(limit).all()
