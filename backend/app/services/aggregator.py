from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.config import settings
from app.models import SavedSearch, ScrapeRun, Tender, User
from app.parsers import get_parsers
from app.parsers.base import ParsedTender
from app.services.enrich import enrich_tender
from app.services.filters import query_from_filters
from app.services.customers import extract_inn, extract_kpp, upsert_customer
from app.services.health import record_source_run
from app.services.history import content_hash_for, record_changes
from app.services.normalize import (
    extract_okpd2,
    make_fingerprint,
    normalize_price,
    normalize_region,
    normalize_status,
    normalize_text,
)
from app.services.queue import scrape_queue, with_retries
from app.services.seed import build_demo_tenders, seed_if_empty, seed_presets
from app.services.telegram import notify_new_tenders


def _deadline_passed(deadline_at: datetime | None, now: datetime) -> bool:
    if deadline_at is None:
        return False
    if deadline_at.tzinfo is None:
        deadline_at = deadline_at.replace(tzinfo=timezone.utc)
    return deadline_at < now


def _snapshot(tender: Tender) -> dict:
    return {
        "price": tender.price,
        "deadline_at": tender.deadline_at,
        "status": tender.status,
        "status_norm": tender.status_norm,
        "title": tender.title,
        "region": tender.region,
        "method": tender.method,
    }


def _apply_normalized_fields(tender: Tender, item: ParsedTender, now: datetime) -> str:
    title = normalize_text(item.title) or item.title
    customer = normalize_text(item.customer)
    region = normalize_region(item.region)
    price = normalize_price(item.price)
    method = normalize_text(item.method)
    description = normalize_text(item.description)
    okpd2 = item.okpd2 or extract_okpd2(description) or extract_okpd2(title)
    status_norm, status_label = normalize_status(
        item.status, deadline_passed=_deadline_passed(item.deadline_at, now)
    )
    fingerprint = make_fingerprint(title, customer, price, region)
    c_hash = content_hash_for(title, price, status_label, item.deadline_at, region, method)

    tender.external_id = item.external_id
    tender.source = item.source
    tender.law = item.law or tender.law
    tender.title = title
    tender.customer = customer or tender.customer
    tender.customer_inn = item.customer_inn or tender.customer_inn
    tender.region = region or tender.region
    tender.price = price if price is not None else tender.price
    tender.currency = item.currency or tender.currency or "RUB"
    tender.status = status_label
    tender.status_norm = status_norm
    tender.method = method or tender.method
    tender.okpd2 = okpd2 or tender.okpd2
    tender.url = item.url
    tender.description = description or tender.description
    if item.documents:
        tender.documents = item.documents
    if item.lots:
        tender.lots = item.lots
    tender.published_at = item.published_at or tender.published_at
    tender.deadline_at = item.deadline_at or tender.deadline_at
    tender.fingerprint = fingerprint
    tender.content_hash = c_hash
    # Infer INN/KPP from customer text if missing
    if not tender.customer_inn:
        tender.customer_inn = item.customer_inn or extract_inn(customer) or extract_inn(description)
    if not tender.customer_kpp:
        tender.customer_kpp = extract_kpp(customer or "") or extract_kpp(description or "")
    return c_hash


def _link_customer(db: Session, tender: Tender, *, bump_stats: bool = True) -> None:
    if not tender.customer and not tender.customer_inn:
        return
    customer = upsert_customer(
        db,
        name=tender.customer,
        inn=tender.customer_inn,
        kpp=tender.customer_kpp,
        region=tender.region,
        price=tender.price,
        bump_stats=bump_stats,
    )
    if customer:
        tender.customer_id = customer.id
        if customer.inn and not tender.customer_inn:
            tender.customer_inn = customer.inn
        if customer.kpp and not tender.customer_kpp:
            tender.customer_kpp = customer.kpp


def _mark_duplicates(db: Session, fingerprint: str, keeper_id: int) -> None:
    if not fingerprint:
        return
    others = (
        db.query(Tender)
        .filter(Tender.fingerprint == fingerprint, Tender.id != keeper_id)
        .all()
    )
    for other in others:
        if other.id < keeper_id:
            keeper = other
            duplicate = db.get(Tender, keeper_id)
            if duplicate:
                duplicate.is_duplicate = True
                duplicate.duplicate_of_id = keeper.id
            other.is_duplicate = False
            other.duplicate_of_id = None
        else:
            other.is_duplicate = True
            other.duplicate_of_id = keeper_id


def upsert_tenders_collect_new(db: Session, items: list[ParsedTender]) -> tuple[int, int, list[int], list[int]]:
    """Returns (upserted, skipped_unchanged, touched_ids, brand_new_ids)."""
    upserted = 0
    skipped = 0
    touched_ids: list[int] = []
    new_ids: list[int] = []
    now = datetime.now(timezone.utc)

    for item in items:
        existing = (
            db.query(Tender)
            .filter(Tender.source == item.source, Tender.external_id == item.external_id)
            .one_or_none()
        )
        if existing is None:
            tender = Tender(
                external_id=item.external_id,
                source=item.source,
                title=item.title,
                url=item.url,
                documents=item.documents or [],
                lots=item.lots or [],
                is_duplicate=False,
            )
            _apply_normalized_fields(tender, item, now)
            db.add(tender)
            db.flush()
            _link_customer(db, tender, bump_stats=True)
            _mark_duplicates(db, tender.fingerprint or "", tender.id)
            upserted += 1
            touched_ids.append(tender.id)
            new_ids.append(tender.id)
            continue

        before = _snapshot(existing)
        new_hash = content_hash_for(
            normalize_text(item.title) or item.title,
            normalize_price(item.price),
            normalize_status(item.status, _deadline_passed(item.deadline_at, now))[1],
            item.deadline_at,
            normalize_region(item.region),
            normalize_text(item.method),
        )
        if existing.content_hash and existing.content_hash == new_hash:
            skipped += 1
            _link_customer(db, existing, bump_stats=False)
            continue

        _apply_normalized_fields(existing, item, now)
        existing.is_duplicate = False
        db.flush()
        _link_customer(db, existing, bump_stats=True)
        record_changes(db, existing, before)
        _mark_duplicates(db, existing.fingerprint or "", existing.id)
        upserted += 1
        touched_ids.append(existing.id)

    now = datetime.now(timezone.utc)
    overdue = (
        db.query(Tender)
        .filter(
            Tender.status_norm == "accepting",
            Tender.deadline_at.isnot(None),
            Tender.deadline_at < now,
        )
        .limit(500)
        .all()
    )
    for tender in overdue:
        before = _snapshot(tender)
        tender.status_norm = "completed"
        tender.status = "Завершён"
        record_changes(db, tender, before)

    db.commit()
    return upserted, skipped, touched_ids, new_ids


# Keep original upsert for callers that don't need new ids — redirect to collect_new
def upsert_tenders(db: Session, items: list[ParsedTender]) -> tuple[int, int, list[int]]:
    upserted, skipped, touched, _new = upsert_tenders_collect_new(db, items)
    return upserted, skipped, touched


async def _fetch_source(source_id: str) -> list[ParsedTender]:
    parser = get_parsers().get(source_id)
    if parser is None:
        return []

    async def _do():
        return await parser.fetch()

    return await with_retries(_do)


def _is_source_fail_fast(db: Session, source_id: str) -> bool:
    from datetime import timedelta

    from app.models import SourceHealth

    row = db.query(SourceHealth).filter(SourceHealth.source == source_id).one_or_none()
    if not row:
        return False
    if (row.consecutive_failures or 0) < settings.fail_fast_failures:
        return False
    # Half-open: re-probe after 2 scrape intervals without a real attempt
    if row.last_run_at:
        age = datetime.now(timezone.utc) - (
            row.last_run_at if row.last_run_at.tzinfo else row.last_run_at.replace(tzinfo=timezone.utc)
        )
        if age > timedelta(minutes=settings.scrape_interval_minutes * 2):
            return False
    return True


async def _update_saved_searches_and_notify(db: Session) -> None:
    searches = db.query(SavedSearch).all()
    for search in searches:
        matched = query_from_filters(db, search.filters or {}).order_by(Tender.id.desc()).limit(100).all()
        ids = [t.id for t in matched]
        prev = set(search.last_seen_ids or [])
        new_ids = [i for i in ids if i not in prev]
        search.new_count = len(new_ids)
        if new_ids:
            search.last_seen_ids = (list(prev) + new_ids)[-500:]
            user = db.get(User, search.user_id)
            if (
                search.notify_telegram
                and user
                and user.telegram_chat_id
                and settings.telegram_bot_token
            ):
                new_tenders = [t for t in matched if t.id in set(new_ids)]
                await notify_new_tenders(user.telegram_chat_id, search.name, new_tenders)
    db.commit()


async def _scrape_one_source(db: Session, source_id: str) -> tuple[ScrapeRun, list[int], list[int]]:
    """Scrape a single source; returns run, touched ids, brand-new ids."""
    run = ScrapeRun(source=source_id, status="running", fetched=0, upserted=0, skipped=0)
    db.add(run)
    db.commit()
    db.refresh(run)
    touched: list[int] = []
    new_ids: list[int] = []

    if _is_source_fail_fast(db, source_id):
        run.status = "skipped"
        run.error = f"fail-fast: {settings.fail_fast_failures}+ consecutive failures"
        run.finished_at = datetime.now(timezone.utc)
        db.commit()
        db.refresh(run)
        record_source_run(db, run)
        return run, touched, new_ids

    try:
        items = await _fetch_source(source_id)
        if not items:
            items = [t for t in build_demo_tenders(8) if t.source == source_id]
            if not items:
                # Don't inject unrelated commercial demos into the niche feed
                run.error = "Источник недоступен или пуст"
                run.status = "fallback"
                run.fetched = 0
                run.upserted = 0
                run.skipped = 0
            else:
                run.error = "Источник недоступен или пуст — загружены демо-данные"
        if items:
            upserted, skipped, touched, new_ids = upsert_tenders_collect_new(db, items)
            run.fetched = len(items)
            run.upserted = upserted
            run.skipped = skipped
            run.status = "ok" if not run.error else "fallback"
        elif run.status == "running":
            run.fetched = 0
            run.upserted = 0
            run.skipped = 0
            run.status = "ok"
            run.error = "Источник пуст"
    except Exception as exc:  # noqa: BLE001
        items = [t for t in build_demo_tenders(8) if t.source == source_id]
        if items:
            upserted, skipped, touched, new_ids = upsert_tenders_collect_new(db, items)
            run.fetched = len(items)
            run.upserted = upserted
            run.skipped = skipped
            run.status = "fallback"
            run.error = str(exc)[:1000]
        else:
            touched, new_ids = [], []
            run.fetched = 0
            run.upserted = 0
            run.skipped = 0
            run.status = "fallback"
            run.error = str(exc)[:1000]

    run.finished_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(run)
    record_source_run(db, run)
    return run, touched, new_ids


async def run_scrape(db: Session, source_ids: list[str] | None = None) -> list[ScrapeRun]:
    async def _job() -> list[ScrapeRun]:
        import asyncio

        from app.services.cache import cache_clear
        from app.services.jobs import enqueue_job

        parsers = get_parsers()
        selected = source_ids or list(parsers.keys())
        selected = [s for s in selected if s in parsers]
        runs: list[ScrapeRun] = []
        all_new: list[int] = []
        all_touched: list[int] = []
        sem = asyncio.Semaphore(settings.scrape_concurrency)

        async def _guarded(sid: str) -> tuple[ScrapeRun, list[int], list[int]]:
            async with sem:
                # Each parallel task needs its own session for thread-safety
                from app.database import SessionLocal

                local = SessionLocal()
                try:
                    return await _scrape_one_source(local, sid)
                finally:
                    local.close()

        results = await asyncio.gather(*[_guarded(sid) for sid in selected], return_exceptions=True)
        for sid, result in zip(selected, results):
            if isinstance(result, BaseException):
                run = ScrapeRun(
                    source=sid,
                    status="fallback",
                    fetched=0,
                    upserted=0,
                    skipped=0,
                    error=str(result)[:1000],
                    finished_at=datetime.now(timezone.utc),
                )
                db.add(run)
                db.commit()
                db.refresh(run)
                record_source_run(db, run)
                runs.append(run)
                continue
            run, touched, new_ids = result
            runs.append(run)
            all_new.extend(new_ids)
            all_touched.extend(touched)

        enrich_ids = all_new if settings.enrich_new_only else all_touched
        if settings.enrich_on_scrape and enrich_ids:
            for tender_id in enrich_ids[: settings.enrich_limit_per_scrape]:
                tender = db.get(Tender, tender_id)
                if tender and tender.source.startswith("zakupki"):
                    try:
                        await enrich_tender(db, tender, force=False)
                    except Exception:  # noqa: BLE001
                        pass
        elif enrich_ids:
            # Queue enrich separately with lower priority
            enqueue_job(
                db,
                "enrich",
                {"tender_ids": enrich_ids[: settings.enrich_limit_per_scrape]},
                priority=200,
            )

        seed_if_empty(db)
        seed_presets(db)
        await _update_saved_searches_and_notify(db)
        cache_clear("api:")
        return runs

    return await scrape_queue.run(_job)

