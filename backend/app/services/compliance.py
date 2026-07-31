from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.models import Tender
from app.services.customers import extract_inn, upsert_customer


def check_compliance(db: Session, inn: str | None, name: str | None = None) -> dict:
    inn = (inn or "").strip() or extract_inn(name)
    now = datetime.now(timezone.utc)
    notes: list[str] = []

    rnp_hits = []
    guarantee_hits = []
    if inn:
        rnp_hits = (
            db.query(Tender)
            .filter(
                Tender.source == "rnp",
                or_(
                    Tender.customer_inn == inn,
                    Tender.title.ilike(f"%{inn}%"),
                    Tender.description.ilike(f"%{inn}%"),
                ),
            )
            .limit(5)
            .all()
        )
        guarantee_hits = (
            db.query(Tender)
            .filter(
                Tender.source == "bank_guarantees",
                or_(
                    Tender.customer_inn == inn,
                    Tender.title.ilike(f"%{inn}%"),
                    Tender.description.ilike(f"%{inn}%"),
                ),
            )
            .limit(5)
            .all()
        )

    in_rnp = bool(rnp_hits)
    has_bg = bool(guarantee_hits) if guarantee_hits else None
    if in_rnp:
        notes.append(f"Найдены записи РНП: {len(rnp_hits)}")
    else:
        notes.append("В локальном РНП совпадений нет")
    if has_bg:
        notes.append(f"Найдены записи банка гарантий: {len(guarantee_hits)}")
    else:
        notes.append("По банку гарантий данных нет")

    customer = None
    if inn or name:
        customer = upsert_customer(db, name=name or f"ИНН {inn}", inn=inn)
        if customer:
            customer.in_rnp = in_rnp
            customer.has_bank_guarantee = has_bg
            customer.compliance_checked_at = now
            customer.compliance_notes = "; ".join(notes)
            db.commit()
            db.refresh(customer)

    return {
        "inn": inn,
        "in_rnp": in_rnp,
        "has_bank_guarantee": has_bg,
        "checked_at": now.isoformat(),
        "notes": "; ".join(notes),
        "rnp_items": [
            {
                "id": t.id,
                "title": t.title,
                "url": t.url,
                "published_at": t.published_at.isoformat() if t.published_at else None,
            }
            for t in rnp_hits
        ],
        "guarantee_items": [
            {
                "id": t.id,
                "title": t.title,
                "url": t.url,
                "published_at": t.published_at.isoformat() if t.published_at else None,
            }
            for t in guarantee_hits
        ],
        "customer_id": customer.id if customer else None,
    }


async def check_tender_compliance(db: Session, tender: Tender) -> dict:
    result = check_compliance(db, tender.customer_inn, tender.customer)
    if tender.customer_id is None and result.get("customer_id"):
        tender.customer_id = result["customer_id"]
        db.commit()
    return result
