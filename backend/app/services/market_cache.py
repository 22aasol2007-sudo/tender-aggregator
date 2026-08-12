from __future__ import annotations

import hashlib
import math
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

# Category keyword → TTL days (stale-price control)
_CATEGORY_TTL = (
    (("полиэтилен", "сырь", "гранул", "смол", "металл", "сталь"), 5),
    (("гофр", "упаков", "картон", "пленк", "плёнк", "короб"), 10),
    (("перевоз", "логист", "фрахт", "транспорт"), 14),
)

SOURCE_TRUST = {
    "contract": 0.9,
    "firm_rfq": 0.85,
    "rfq": 0.75,
    "manual": 0.7,
    "estimate": 0.35,
}

PRICE_LAYERS = ("estimate", "observed", "firm")


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


def ttl_days_for(product_or_category: str | None = None) -> int:
    default = max(1, int(getattr(settings, "market_cache_ttl_days", 14)))
    text = (product_or_category or "").casefold()
    for keys, days in _CATEGORY_TTL:
        if any(k in text for k in keys):
            return days
    return default


def _expires_at(product: str | None = None, from_dt: datetime | None = None) -> datetime:
    base = from_dt or datetime.now(timezone.utc)
    return base + timedelta(days=ttl_days_for(product))


def _aware(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def _age_days(observed_at: datetime | None, now: datetime) -> float | None:
    obs = _aware(observed_at)
    if obs is None:
        return None
    return max(0.0, (now - obs).total_seconds() / 86400.0)


def _freshness(age_days: float | None, ttl: int) -> str:
    if age_days is None:
        return "unknown"
    if age_days <= ttl * 0.5:
        return "fresh"
    if age_days <= ttl:
        return "aging"
    return "stale"


def resolve_price_layer(source_type: str | None, explicit: str | None = None) -> str:
    if explicit in PRICE_LAYERS:
        return explicit
    st = (source_type or "").casefold()
    if st in {"firm", "firm_rfq"}:
        return "firm"
    if st in {"estimate", "model", "ai_estimate"}:
        return "estimate"
    return "observed"


def trust_for_source(source_type: str | None, confidence: float | None = None) -> float:
    base = SOURCE_TRUST.get((source_type or "rfq").casefold(), 0.55)
    if confidence is None:
        return base
    return round(min(0.99, max(0.05, 0.5 * base + 0.5 * float(confidence))), 3)


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
        "user_id",
        "buyer",
        "заказчик",
    }
    clean: dict[str, Any] = {}
    for k, v in payload.items():
        if k.casefold() in banned:
            continue
        if isinstance(v, str) and ("@" in v or re.search(r"\+?\d[\d\-\s]{8,}\d", v)):
            continue
        clean[k] = v
    return clean


def _bucket_price(value: float | None, share_consent: bool) -> float | None:
    """Coarse price buckets when sharing across clients."""
    if value is None or not share_consent:
        return value
    if value <= 0:
        return value
    # ~5% bucket to reduce exact commercial-secret leakage
    exp = 10 ** max(0, int(math.floor(math.log10(value))) - 1)
    step = max(exp, value * 0.05)
    return round(round(value / step) * step, 2)


def _min_trust() -> float:
    return float(getattr(settings, "market_cache_min_trust", 0.6))


def _min_share_n() -> int:
    return max(1, int(getattr(settings, "market_cache_min_share_n", 5)))


def _offer_comparable(raw: dict[str, Any]) -> bool:
    """Offer is comparable only with unit + price present."""
    if raw.get("incomparable") is True:
        return False
    if raw.get("price_value") is None and raw.get("landed_unit_price") is None:
        return False
    unit = (raw.get("unit") or "").strip()
    if not unit:
        return False
    return True


def _quarantine_reason(
    *,
    price: float | None,
    peer_prices: list[float],
    trust: float,
) -> str | None:
    if trust < _min_trust():
        return "low_trust"
    if price is None or len(peer_prices) < 4:
        return None
    ordered = sorted(peer_prices)
    p10 = ordered[max(0, int(0.1 * (len(ordered) - 1)))]
    p90 = ordered[min(len(ordered) - 1, int(0.9 * (len(ordered) - 1)))]
    if price < p10 * 0.7 or price > p90 * 1.4:
        return "price_outlier"
    return None


def lookup_market_cache(
    db: Session,
    *,
    product: str,
    city: str | None = None,
    qty: float | None = None,
    unit: str | None = None,
    allow_stale: bool = False,
    include_quarantined: bool = False,
) -> dict[str, Any]:
    meta = build_fingerprint(product=product, city=city, qty=qty, unit=unit)
    now = datetime.now(timezone.utc)
    ttl = ttl_days_for(product)
    row = db.query(MarketQueryCache).filter(MarketQueryCache.fingerprint == meta["fingerprint"]).first()

    match_type = "exact"
    if row is None:
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
                "match_type": None,
                "price_layers_note": (
                    "estimate=оценка, observed=кэш/контракт, firm=свежий ответ поставщику. "
                    "Для сделки нужен firm."
                ),
                "orchestration": {
                    "next": "warm_rfq",
                    "steps": [
                        "client_supplier_book",
                        "contract_winners",
                        "limited_cold_rfq",
                    ],
                    "avoid": ["deep_search_default", "autoselect_winner"],
                },
                "offers": [],
                "summary": None,
                "ttl_days": ttl,
            }
        row = soft
        match_type = "soft"

    expired_at = _aware(row.expires_at)
    age = _age_days(row.updated_at or row.created_at, now)
    freshness = _freshness(age, ttl)
    if freshness == "stale" and not allow_stale:
        return {
            "hit": False,
            "reason": "expired",
            "fingerprint": row.fingerprint,
            "meta": meta,
            "match_type": match_type,
            "freshness": freshness,
            "age_days": round(age, 2) if age is not None else None,
            "ttl_days": ttl,
            "offers": [],
            "summary": row.result_summary,
            "expires_at": row.expires_at,
            "warning": "Кэш устарел. Нужен refresh RFQ; не используйте как firm.",
            "orchestration": {"next": "refresh_rfq", "steps": ["cached_shortlist_as_hint", "fresh_rfq"]},
            "price_layers_note": (
                "estimate=оценка, observed=кэш/контракт, firm=свежий ответ поставщику."
            ),
        }

    q = db.query(MarketOfferObservation).filter(
        or_(
            MarketOfferObservation.query_cache_id == row.id,
            MarketOfferObservation.fingerprint == row.fingerprint,
        )
    )
    if not include_quarantined:
        q = q.filter(MarketOfferObservation.quarantined.is_(False))
    q = q.filter(MarketOfferObservation.trust_score >= _min_trust())
    # Cross-client safety: never leak firm / private rows via shared lookup
    q = q.filter(
        MarketOfferObservation.shareable.is_(True),
        MarketOfferObservation.price_layer != "firm",
    )
    offers = (
        q.order_by(
            MarketOfferObservation.landed_unit_price.asc().nullslast(),
            MarketOfferObservation.id.desc(),
        )
        .limit(40)
        .all()
    )

    min_n = _min_share_n()
    anonymized = False
    if 0 < len(offers) < min_n:
        # k-anonymity: too few shared observations → aggregate only
        prices = [o.landed_unit_price or o.price_value for o in offers if (o.landed_unit_price or o.price_value)]
        prices = [float(p) for p in prices if p is not None]
        anonymized = True
        offer_dicts = []
        agg_summary = dict(row.result_summary or {})
        if prices:
            ordered = sorted(prices)
            agg_summary.update(
                {
                    "anonymized": True,
                    "n": len(prices),
                    "median_price": ordered[len(ordered) // 2],
                    "min_price": ordered[0],
                    "max_price": ordered[-1],
                    "note": f"Мало наблюдений (<{min_n}) — без имён поставщиков",
                }
            )
        summary_out = agg_summary
    else:
        offer_dicts = [_offer_dict(o, now=now, ttl=ttl) for o in offers]
        summary_out = row.result_summary or {}

    # Soft match: never present as actionable cache answer
    actionable = match_type == "exact" and freshness in {"fresh", "aging"} and (
        bool(offer_dicts) or anonymized
    )

    saved = int(getattr(settings, "market_cache_tokens_saved_per_hit", 120_000))
    if actionable:
        row.hit_count = int(row.hit_count or 0) + 1
        row.token_saved_estimate = int(row.token_saved_estimate or 0) + saved
        db.commit()

    if match_type == "soft":
        for o in offer_dicts:
            if o.get("price_layer") == "firm":
                o["price_layer"] = "observed"
            o["warning"] = "soft_match: не firm для текущего запроса"

    return {
        "hit": actionable,
        "reason": "hit"
        if actionable and match_type == "exact"
        else ("soft_hint" if match_type == "soft" else freshness),
        "match_type": match_type,
        "fingerprint": row.fingerprint,
        "meta": {
            "category_key": row.category_key,
            "city_key": row.city_key,
            "qty_band": row.qty_band,
            "unit": row.unit,
        },
        "summary": summary_out,
        "anonymized": anonymized,
        "offer_count": len(offer_dicts),
        "hit_count": row.hit_count,
        "token_saved_estimate": row.token_saved_estimate,
        "tokens_saved_this_hit": saved if actionable else 0,
        "expires_at": row.expires_at,
        "updated_at": row.updated_at,
        "freshness": freshness,
        "age_days": round(age, 2) if age is not None else None,
        "ttl_days": ttl,
        "warning": (
            "Похожий запрос (soft) — только ориентир, не ответ."
            if match_type == "soft"
            else (
                "Мало наблюдений — показана только агрегированная статистика."
                if anonymized
                else (
                    None
                    if actionable and freshness == "fresh"
                    else "Кэш стареет — рекомендуется refresh перед сделкой."
                )
            )
        ),
        "price_layers_note": (
            "estimate=оценка; observed=кэш/история; firm=свежий ответ этому клиенту. "
            "Сделка только на firm."
        ),
        "orchestration": {
            "next": "use_cache" if actionable and offer_dicts else "warm_rfq",
            "allow_autoselect": False,
            "require_firm_for_deal": True,
            "steps": ["show_observed"]
            if actionable and offer_dicts
            else ["show_aggregate_or_hint", "client_book", "fresh_rfq"],
        },
        "offers": offer_dicts,
    }


def _offer_dict(o: MarketOfferObservation, *, now: datetime, ttl: int) -> dict[str, Any]:
    age = _age_days(o.observed_at, now)
    layer = o.price_layer or resolve_price_layer(o.source_type)
    return {
        "id": o.id,
        "source_type": o.source_type,
        "price_layer": layer,
        "trust_score": o.trust_score,
        "quarantined": bool(o.quarantined),
        "incomparable": bool(o.incomparable),
        "shareable": bool(o.shareable),
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
        "age_days": round(age, 2) if age is not None else None,
        "freshness": _freshness(age, ttl),
        "payload": o.payload or {},
        "disclaimer": "Не оферта. Для сделки нужен firm RFQ."
        if layer != "firm"
        else "Firm-оффер: проверьте срок действия КП.",
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
    share_consent: bool = False,
) -> dict[str, Any]:
    meta = build_fingerprint(product=product, city=city, qty=qty, unit=unit)
    now = datetime.now(timezone.utc)
    ttl = ttl_days_for(product)
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
            expires_at=_expires_at(product, now),
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
        row.expires_at = _expires_at(product, now)

    # Peer prices for outlier detection (existing + incoming)
    existing_prices = [
        p
        for (p,) in db.query(MarketOfferObservation.landed_unit_price)
        .filter(
            MarketOfferObservation.fingerprint == meta["fingerprint"],
            MarketOfferObservation.landed_unit_price.isnot(None),
            MarketOfferObservation.quarantined.is_(False),
        )
        .all()
        if p is not None
    ]
    incoming_prices = [
        float(o["landed_unit_price"])
        for o in (offers or [])
        if o.get("landed_unit_price") is not None
    ] + [
        float(o["price_value"])
        for o in (offers or [])
        if o.get("landed_unit_price") is None and o.get("price_value") is not None
    ]
    peer_prices = existing_prices + incoming_prices

    source_mix: dict[str, int] = dict(row.source_mix or {})
    saved_offers = 0
    skipped_private = 0
    quarantined_n = 0
    for raw in offers or []:
        source_type = str(raw.get("source_type") or "rfq")[:32]
        layer = resolve_price_layer(source_type, raw.get("price_layer"))
        # Firm is always client-specific: store but never auto-share
        want_share = bool(share_consent) and layer != "firm" and source_type != "firm_rfq"
        trust = trust_for_source(source_type, raw.get("confidence"))
        if raw.get("trust_score") is not None:
            trust = float(raw["trust_score"])

        price = raw.get("landed_unit_price")
        if price is None:
            price = raw.get("price_value")
        q_reason = _quarantine_reason(price=price if price is None else float(price), peer_prices=peer_prices, trust=trust)
        quarantined = q_reason is not None
        comparable = _offer_comparable(raw)

        # k-anonymity enforced at lookup; with consent mark observed/contract shareable
        shareable = want_share
        if want_share and layer == "estimate":
            shareable = False  # estimates are weak — do not pollute shared market

        price_value = raw.get("price_value")
        landed = raw.get("landed_unit_price")
        if shareable:
            price_value = _bucket_price(price_value if price_value is None else float(price_value), True)
            landed = _bucket_price(landed if landed is None else float(landed), True)

        obs = MarketOfferObservation(
            fingerprint=meta["fingerprint"],
            query_cache_id=row.id,
            source_type=source_type,
            price_layer=layer,
            trust_score=trust,
            quarantined=quarantined,
            quarantine_reason=q_reason,
            shareable=shareable,
            incomparable=not comparable,
            supplier_name=(raw.get("supplier_name") or None),
            supplier_inn=(raw.get("supplier_inn") or None),
            city_from=raw.get("city_from"),
            city_to=raw.get("city_to") or meta["city_key"] or None,
            unit=raw.get("unit") or unit,
            qty=raw.get("qty") if raw.get("qty") is not None else qty,
            price_value=price_value,
            currency=raw.get("currency") or "RUB",
            vat=raw.get("vat"),
            delivery_price=raw.get("delivery_price"),
            landed_unit_price=landed,
            lead_time_days=raw.get("lead_time_days"),
            payment_terms=raw.get("payment_terms"),
            confidence=float(raw.get("confidence") or 0.7),
            payload=_sanitize_payload(raw.get("payload") if isinstance(raw.get("payload"), dict) else raw),
            observed_at=now,
            expires_at=_expires_at(product, now),
        )
        db.add(obs)
        saved_offers += 1
        if quarantined:
            quarantined_n += 1
        if not shareable and want_share is False and layer == "firm":
            skipped_private += 0  # firm saved but private by layer
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
        "quarantined": quarantined_n,
        "offer_count": row.offer_count,
        "expires_at": row.expires_at,
        "ttl_days": ttl,
        "share_consent_applied": bool(share_consent),
        "note": "Firm-офферы не шарятся между клиентами. Soft/HIT учитывает trust и TTL.",
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
                    "price_layer": "observed",
                    "supplier_name": c.supplier_name,
                    "supplier_inn": c.supplier_inn,
                    "city_to": c.region,
                    "unit": "lot",
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
            "price_layer_default": "observed",
        }
        res = save_market_result(
            db,
            product=sample.title,
            city=sample.region,
            offers=offers,
            summary=summary,
            query_raw=sample.title,
            share_consent=True,  # public EIS awards
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
