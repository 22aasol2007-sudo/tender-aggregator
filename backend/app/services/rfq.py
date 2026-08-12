from __future__ import annotations

import secrets
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.config import settings
from app.models import (
    ClientSupplierBook,
    CompanyProfile,
    MarketOfferObservation,
    RfqDealConfirmation,
    RfqRequest,
    RfqTarget,
    SourcingExecutionFeedback,
    User,
)
from app.services.cosmetics_gofra_niche import (
    DESIGN_PARTNER_RULES,
    attrs_fingerprint_part,
    normalize_gofra_attrs,
)
from app.services.market_cache import (
    build_fingerprint,
    lookup_market_cache,
    resolve_price_layer,
    save_market_result,
    trust_for_source,
)
from app.services.normalize import normalize_text


def _now() -> datetime:
    return datetime.now(timezone.utc)


def create_rfq(
    db: Session,
    *,
    user: User,
    product: str,
    city: str | None = "Москва",
    qty: float | None = None,
    unit: str | None = "шт",
    attrs: dict | None = None,
    notes: str | None = None,
    max_cold: int | None = None,
) -> RfqRequest:
    attrs_n = normalize_gofra_attrs(attrs)
    meta = build_fingerprint(product=product, city=city, qty=qty, unit=unit, attrs=attrs_n)
    cold_limit = max_cold
    if cold_limit is None:
        cold_limit = int(getattr(settings, "rfq_max_cold_targets", 6))

    profile = db.query(CompanyProfile).filter(CompanyProfile.user_id == user.id).one_or_none()
    private_only = bool(getattr(profile, "private_only", False)) if profile else False
    share_consent = (
        bool(getattr(profile, "share_consent", False)) and not private_only if profile else False
    )

    req = RfqRequest(
        user_id=user.id,
        product=product.strip(),
        city=(city or "Москва").strip(),
        qty=qty,
        unit=unit or "шт",
        attrs=attrs_n,
        fingerprint=meta["fingerprint"],
        status="draft",
        notes=notes,
        form_token=secrets.token_urlsafe(24),
        max_cold_targets=cold_limit,
        share_consent=share_consent,
        private_only=private_only,
    )
    db.add(req)
    db.flush()

    # Warm-first targets from private book
    book = (
        db.query(ClientSupplierBook)
        .filter(ClientSupplierBook.user_id == user.id)
        .order_by(ClientSupplierBook.updated_at.desc())
        .limit(30)
        .all()
    )
    existing_inns: set[str] = set()
    for b in book:
        db.add(
            RfqTarget(
                rfq_id=req.id,
                source="client_book",
                supplier_name=b.name,
                supplier_inn=b.supplier_inn,
                contact_email=(b.contacts or {}).get("email"),
                contact_phone=(b.contacts or {}).get("phone"),
                status="queued",
                warm=True,
            )
        )
        if b.supplier_inn:
            existing_inns.add(b.supplier_inn)

    # Observed cache suppliers as warm-ish hints (no email until enriched)
    cached = lookup_market_cache(
        db,
        product=product,
        city=city,
        qty=qty,
        unit=unit,
        attrs=attrs_n,
        private_only=private_only,
        user_id=user.id,
        niche_pilot=True,
    )
    for o in cached.get("offers") or []:
        inn = o.get("supplier_inn")
        if inn and inn in existing_inns:
            continue
        db.add(
            RfqTarget(
                rfq_id=req.id,
                source="market_cache",
                supplier_name=o.get("supplier_name"),
                supplier_inn=inn,
                status="queued",
                warm=False,
            )
        )
        if inn:
            existing_inns.add(inn)

    db.commit()
    db.refresh(req)
    return req


def rfq_form_url(req: RfqRequest) -> str:
    base = getattr(settings, "public_app_url", "") or ""
    return f"{base.rstrip('/')}/rfq/form/{req.form_token}"


def build_outreach_drafts(req: RfqRequest) -> list[dict[str, Any]]:
    """Warm-first ordered drafts; cold capped. Phone/WA fallback when email missing."""
    warm = [t for t in (req.targets or []) if t.warm]
    cold = [t for t in (req.targets or []) if not t.warm][: req.max_cold_targets]
    ordered = warm + cold
    attrs = req.attrs or {}
    attr_line = ", ".join(f"{k}={v}" for k, v in attrs.items()) if attrs else ""
    drafts = []
    for t in ordered:
        body = (
            f"Добрый день!\n\n"
            f"Запрос КП: {req.product}\n"
            f"Город поставки: {req.city}\n"
            f"Количество: {req.qty or '—'} {req.unit or ''}\n"
        )
        if attr_line:
            body += f"Параметры: {attr_line}\n"
        form = rfq_form_url(req)
        body += (
            f"\nПросим указать: цена за единицу (с НДС/без), МОД, срок, "
            f"город отгрузки, стоимость доставки до {req.city}.\n"
            f"Удобная форма ответа: {form}\n"
        )
        channel = "email" if t.contact_email else ("phone" if t.contact_phone else "manual")
        drafts.append(
            {
                "target_id": t.id,
                "supplier_name": t.supplier_name,
                "supplier_inn": t.supplier_inn,
                "warm": t.warm,
                "source": t.source,
                "email": t.contact_email,
                "phone": t.contact_phone,
                "channel": channel,
                "subject": f"Запрос КП: {req.product} / {req.city}",
                "body": body,
                "whatsapp_hint": (
                    f"https://wa.me/{''.join(c for c in (t.contact_phone or '') if c.isdigit())}"
                    if t.contact_phone
                    else None
                ),
            }
        )
    return drafts


def mark_rfq_sent(db: Session, req: RfqRequest, target_ids: list[int] | None = None) -> RfqRequest:
    q = db.query(RfqTarget).filter(RfqTarget.rfq_id == req.id)
    if target_ids:
        q = q.filter(RfqTarget.id.in_(target_ids))
    now = _now()
    for t in q.all():
        t.status = "sent"
        t.sent_at = now
    req.status = "sent"
    req.sent_at = now
    db.commit()
    db.refresh(req)
    return req


def ingest_rfq_response(
    db: Session,
    *,
    form_token: str,
    supplier_name: str,
    supplier_inn: str | None = None,
    unit: str | None = None,
    qty: float | None = None,
    price_value: float | None = None,
    currency: str = "RUB",
    vat: str | None = None,
    delivery_price: float | None = None,
    lead_time_days: int | None = None,
    payment_terms: str | None = None,
    city_from: str | None = None,
    raw_message: str | None = None,
) -> dict[str, Any]:
    req = db.query(RfqRequest).filter(RfqRequest.form_token == form_token).first()
    if not req:
        raise ValueError("RFQ not found")
    if req.status in {"cancelled", "closed"}:
        raise ValueError("RFQ closed")

    landed = None
    if price_value is not None:
        landed = float(price_value)
        if delivery_price is not None and qty:
            try:
                landed = float(price_value) + float(delivery_price) / float(qty)
            except (TypeError, ValueError, ZeroDivisionError):
                landed = float(price_value)

    incomparable = not (unit and (price_value is not None))
    target = None
    if supplier_inn:
        target = (
            db.query(RfqTarget)
            .filter(RfqTarget.rfq_id == req.id, RfqTarget.supplier_inn == supplier_inn)
            .first()
        )
    if target is None and supplier_name:
        target = (
            db.query(RfqTarget)
            .filter(RfqTarget.rfq_id == req.id, RfqTarget.supplier_name.ilike(supplier_name.strip()))
            .first()
        )
    if target:
        target.status = "responded"
        target.responded_at = _now()
        target.response_payload = {
            "price_value": price_value,
            "unit": unit,
            "delivery_price": delivery_price,
            "lead_time_days": lead_time_days,
            "vat": vat,
            "payment_terms": payment_terms,
            "city_from": city_from,
            "raw_message": (raw_message or "")[:2000],
        }

    offer = {
        "source_type": "firm_rfq",
        "price_layer": "firm",
        "supplier_name": supplier_name,
        "supplier_inn": supplier_inn,
        "city_from": city_from,
        "city_to": req.city,
        "unit": unit or req.unit,
        "qty": qty if qty is not None else req.qty,
        "price_value": price_value,
        "currency": currency,
        "vat": vat,
        "delivery_price": delivery_price,
        "landed_unit_price": landed,
        "lead_time_days": lead_time_days,
        "payment_terms": payment_terms,
        "confidence": 0.95,
        "incomparable": incomparable,
        "payload": {"rfq_id": req.id, "via": "supplier_form"},
    }

    # Firm always saved; shared market only if consent and not private_only
    save_market_result(
        db,
        product=req.product,
        city=req.city,
        qty=req.qty,
        unit=req.unit,
        attrs=req.attrs,
        offers=[offer],
        summary={"last_rfq_id": req.id},
        query_raw=req.product,
        share_consent=bool(req.share_consent) and not bool(req.private_only),
        owner_user_id=req.user_id,
    )

    # Also keep a private firm copy marker on request
    req.status = "collecting"
    db.commit()
    return {"ok": True, "rfq_id": req.id, "price_layer": "firm", "incomparable": incomparable, "offer": offer}


def confirm_deal(
    db: Session,
    *,
    user: User,
    rfq_id: int,
    supplier_inn: str | None,
    supplier_name: str | None,
    offer_id: int | None = None,
    accepted_risk: bool = False,
    checklist: dict | None = None,
) -> RfqDealConfirmation:
    """Hard-gate: only firm price_layer can be confirmed for a deal."""
    req = db.query(RfqRequest).filter(RfqRequest.id == rfq_id, RfqRequest.user_id == user.id).first()
    if not req:
        raise ValueError("RFQ not found")

    offer = None
    if offer_id:
        offer = db.get(MarketOfferObservation, offer_id)
    if offer is None:
        q = db.query(MarketOfferObservation).filter(
            MarketOfferObservation.fingerprint == req.fingerprint,
            MarketOfferObservation.price_layer == "firm",
        )
        if supplier_inn:
            q = q.filter(MarketOfferObservation.supplier_inn == supplier_inn)
        elif supplier_name:
            q = q.filter(MarketOfferObservation.supplier_name.ilike(supplier_name))
        offer = q.order_by(MarketOfferObservation.id.desc()).first()

    if offer is None or offer.price_layer != "firm":
        raise ValueError(
            "Сделку можно подтвердить только по firm-офферу (свежий ответ поставщика). "
            "Observed/estimate недостаточно."
        )
    if offer.incomparable:
        raise ValueError("Оффер помечен как несравнимый — дополните единицу/цену")
    if offer.quarantined and not accepted_risk:
        raise ValueError(
            "Оффер в карантине (подозрительная цена). Подтвердите accepted_risk=true после ручной проверки."
        )

    cl = checklist or {}
    required = ["unit_ok", "vat_ok", "delivery_ok", "lead_time_ok", "inn_checked"]
    missing = [k for k in required if not cl.get(k)]
    if missing:
        raise ValueError(f"Чеклист неполный: {', '.join(missing)}")

    conf = RfqDealConfirmation(
        rfq_id=req.id,
        user_id=user.id,
        offer_id=offer.id,
        supplier_name=offer.supplier_name,
        supplier_inn=offer.supplier_inn,
        price_layer="firm",
        accepted_risk=bool(accepted_risk or offer.quarantined),
        checklist=cl,
        status="confirmed",
    )
    req.status = "deal_confirmed"
    db.add(conf)
    db.commit()
    db.refresh(conf)
    return conf


def add_execution_feedback(
    db: Session,
    *,
    user: User,
    confirmation_id: int,
    delivered_on_time: bool | None = None,
    quality_ok: bool | None = None,
    actual_price: float | None = None,
    incident: bool = False,
    notes: str | None = None,
) -> SourcingExecutionFeedback:
    conf = (
        db.query(RfqDealConfirmation)
        .filter(RfqDealConfirmation.id == confirmation_id, RfqDealConfirmation.user_id == user.id)
        .first()
    )
    if not conf:
        raise ValueError("Confirmation not found")
    fb = SourcingExecutionFeedback(
        confirmation_id=conf.id,
        user_id=user.id,
        supplier_inn=conf.supplier_inn,
        delivered_on_time=delivered_on_time,
        quality_ok=quality_ok,
        actual_price=actual_price,
        incident=incident,
        notes=notes,
    )
    db.add(fb)
    # Moat: adjust trust on related offers
    if conf.supplier_inn:
        rows = (
            db.query(MarketOfferObservation)
            .filter(MarketOfferObservation.supplier_inn == conf.supplier_inn)
            .order_by(MarketOfferObservation.id.desc())
            .limit(20)
            .all()
        )
        for r in rows:
            trust = float(r.trust_score or 0.7)
            if incident or quality_ok is False:
                r.trust_score = max(0.05, trust - 0.15)
                if incident:
                    r.quarantined = True
                    r.quarantine_reason = "execution_incident"
            elif delivered_on_time and quality_ok:
                r.trust_score = min(0.99, trust + 0.05)
    db.commit()
    db.refresh(fb)
    return fb


def design_partner_status(db: Session, user_id: int) -> dict[str, Any]:
    confirmed = (
        db.query(RfqDealConfirmation)
        .filter(RfqDealConfirmation.user_id == user_id, RfqDealConfirmation.status == "confirmed")
        .count()
    )
    rules = DESIGN_PARTNER_RULES
    return {
        "free_deals_used": confirmed,
        "free_deals_left": max(0, int(rules["max_free_deals"]) - confirmed),
        "rules": rules,
        "ready_for_paid_hint": confirmed >= int(rules["max_free_deals"]),
    }
