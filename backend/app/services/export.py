from __future__ import annotations

import csv
import io
from datetime import datetime, timedelta, timezone

from openpyxl import Workbook
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models import ScrapeRun, Tender


def dashboard_payload(db: Session) -> dict:
    now = datetime.now(timezone.utc)
    day_ago = now - timedelta(days=1)
    week_ago = now - timedelta(days=7)

    total = db.query(Tender).filter(Tender.is_duplicate.is_(False)).count()
    active = (
        db.query(Tender)
        .filter(Tender.is_duplicate.is_(False), Tender.status_norm == "accepting")
        .count()
    )
    avg_price = (
        db.query(func.avg(Tender.price))
        .filter(Tender.is_duplicate.is_(False), Tender.price.isnot(None))
        .scalar()
    )
    new_day = (
        db.query(Tender)
        .filter(Tender.is_duplicate.is_(False), Tender.created_at >= day_ago)
        .count()
    )
    new_week = (
        db.query(Tender)
        .filter(Tender.is_duplicate.is_(False), Tender.created_at >= week_ago)
        .count()
    )
    changed_day = (
        db.query(Tender)
        .filter(Tender.is_duplicate.is_(False), Tender.changed_at >= day_ago)
        .count()
    )

    top_regions = [
        {"region": r[0], "count": r[1]}
        for r in (
            db.query(Tender.region, func.count(Tender.id))
            .filter(Tender.is_duplicate.is_(False), Tender.region.isnot(None), Tender.region != "")
            .group_by(Tender.region)
            .order_by(func.count(Tender.id).desc())
            .limit(8)
            .all()
        )
    ]
    by_source = {
        row[0]: row[1]
        for row in (
            db.query(Tender.source, func.count(Tender.id))
            .filter(Tender.is_duplicate.is_(False))
            .group_by(Tender.source)
            .all()
        )
    }

    # Simple daily series for last 7 days
    series = []
    for i in range(6, -1, -1):
        start = (now - timedelta(days=i)).replace(hour=0, minute=0, second=0, microsecond=0)
        end = start + timedelta(days=1)
        cnt = (
            db.query(Tender)
            .filter(Tender.is_duplicate.is_(False), Tender.created_at >= start, Tender.created_at < end)
            .count()
        )
        series.append({"date": start.date().isoformat(), "count": cnt})

    last_scrape = db.query(func.max(ScrapeRun.finished_at)).scalar()
    return {
        "total": total,
        "active": active,
        "avg_price": float(avg_price) if avg_price is not None else None,
        "new_day": new_day,
        "new_week": new_week,
        "changed_day": changed_day,
        "top_regions": top_regions,
        "by_source": by_source,
        "series": series,
        "last_scrape": last_scrape,
    }


def tenders_to_csv(rows: list[Tender]) -> bytes:
    buf = io.StringIO()
    writer = csv.writer(buf, delimiter=";")
    writer.writerow(
        [
            "id",
            "source",
            "external_id",
            "title",
            "customer",
            "region",
            "price",
            "status",
            "method",
            "okpd2",
            "deadline_at",
            "url",
        ]
    )
    for t in rows:
        writer.writerow(
            [
                t.id,
                t.source,
                t.external_id,
                t.title,
                t.customer,
                t.region,
                t.price,
                t.status,
                t.method,
                t.okpd2,
                t.deadline_at.isoformat() if t.deadline_at else "",
                t.url,
            ]
        )
    return buf.getvalue().encode("utf-8-sig")


def tenders_to_xlsx(rows: list[Tender]) -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.title = "Tenders"
    headers = [
        "id",
        "source",
        "external_id",
        "title",
        "customer",
        "region",
        "price",
        "status",
        "method",
        "okpd2",
        "deadline_at",
        "url",
    ]
    ws.append(headers)
    for t in rows:
        ws.append(
            [
                t.id,
                t.source,
                t.external_id,
                t.title,
                t.customer,
                t.region,
                t.price,
                t.status,
                t.method,
                t.okpd2,
                t.deadline_at.isoformat() if t.deadline_at else "",
                t.url,
            ]
        )
    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()
