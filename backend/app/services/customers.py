from __future__ import annotations

import re
from datetime import datetime, timezone

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models import Customer, Tender
from app.services.normalize import normalize_region, normalize_text

INN_RE = re.compile(r"\b(\d{10}|\d{12})\b")
KPP_RE = re.compile(r"\b(\d{9})\b")

HOLDING_MARKERS = (
    (r"\bсбербанк\b|\bсбер\b", "Сбер"),
    (r"\bгазпром\b", "Газпром"),
    (r"\bроснефть\b", "Роснефть"),
    (r"\bржд\b|\bроссийские железные дороги\b", "РЖД"),
    (r"\bростелеком\b", "Ростелеком"),
    (r"\bмтс\b", "МТС"),
    (r"\bлукойл\b", "ЛУКОЙЛ"),
    (r"\bминздрав\b|\bминистерство здравоохранения\b", "Минздрав"),
    (r"\bминобороны\b|\bминистерство обороны\b", "Минобороны"),
    (r"\bмвд\b", "МВД"),
)


def extract_inn(text: str | None) -> str | None:
    if not text:
        return None
    m = INN_RE.search(text.replace(" ", ""))
    return m.group(1) if m else None


def extract_kpp(text: str | None) -> str | None:
    if not text:
        return None
    # Prefer explicit KPP label
    labeled = re.search(r"КПП\s*[:\- ]\s*(\d{9})", text, re.I)
    if labeled:
        return labeled.group(1)
    return None


def detect_holding(name: str | None) -> str | None:
    if not name:
        return None
    low = name.lower()
    for pattern, holding in HOLDING_MARKERS:
        if re.search(pattern, low, re.I):
            return holding
    return None


def normalize_customer_name(name: str | None) -> str:
    text = normalize_text(name) or "Неизвестный заказчик"
    text = re.sub(r"\s+", " ", text)
    text = re.sub(r'["«»]', "", text)
    return text[:512]


def upsert_customer(
    db: Session,
    *,
    name: str | None,
    inn: str | None = None,
    kpp: str | None = None,
    region: str | None = None,
    price: float | None = None,
    bump_stats: bool = True,
) -> Customer | None:
    clean_name = normalize_customer_name(name)
    inn = inn or extract_inn(name) or extract_inn(clean_name)
    kpp = kpp or extract_kpp(name or "")
    region = normalize_region(region)
    holding = detect_holding(clean_name)
    now = datetime.now(timezone.utc)

    customer: Customer | None = None
    if inn:
        customer = db.query(Customer).filter(Customer.inn == inn).one_or_none()
    if customer is None:
        customer = (
            db.query(Customer)
            .filter(Customer.name_normalized == clean_name.lower())
            .one_or_none()
        )

    if customer is None:
        customer = Customer(
            inn=inn,
            kpp=kpp,
            name=clean_name,
            name_normalized=clean_name.lower(),
            holding_name=holding,
            region=region,
            tender_count=0,
            total_price=0.0,
        )
        db.add(customer)
        db.flush()
    else:
        if inn and not customer.inn:
            customer.inn = inn
        if kpp and not customer.kpp:
            customer.kpp = kpp
        if region and not customer.region:
            customer.region = region
        if holding and not customer.holding_name:
            customer.holding_name = holding
        # Prefer longer official-looking name
        if len(clean_name) > len(customer.name or ""):
            customer.name = clean_name
            customer.name_normalized = clean_name.lower()

    customer.last_seen_at = now
    if bump_stats:
        customer.tender_count = (customer.tender_count or 0) + 1
        if price:
            customer.total_price = float(customer.total_price or 0) + float(price)
    db.flush()
    return customer


def refresh_customer_stats(db: Session, customer_id: int) -> None:
    customer = db.get(Customer, customer_id)
    if not customer:
        return
    count, total = (
        db.query(func.count(Tender.id), func.coalesce(func.sum(Tender.price), 0.0))
        .filter(Tender.customer_id == customer_id)
        .one()
    )
    customer.tender_count = int(count or 0)
    customer.total_price = float(total or 0)


def customer_history(db: Session, customer_id: int, limit: int = 20) -> list[Tender]:
    return (
        db.query(Tender)
        .filter(Tender.customer_id == customer_id, Tender.is_duplicate.is_(False))
        .order_by(Tender.published_at.desc(), Tender.id.desc())
        .limit(limit)
        .all()
    )
