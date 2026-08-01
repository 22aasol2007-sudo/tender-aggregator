from __future__ import annotations

import time
from collections import defaultdict, deque
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db, is_postgres
from app.models import (
    CompanyProfile,
    Customer,
    FilterPreset,
    SavedSearch,
    ScrapeRun,
    Tender,
    TenderChange,
    TenderWatch,
    User,
    WorkerJob,
)
from app.parsers import list_sources
from app.schemas import (
    CustomerDetailOut,
    CustomerOut,
    DashboardOut,
    FilterPresetIn,
    FilterPresetOut,
    HealthOut,
    JobOut,
    LoginIn,
    NicheOut,
    ProfileIn,
    ProfileOut,
    RegisterIn,
    SavedSearchIn,
    SavedSearchOut,
    ScrapeEnqueueOut,
    ScrapeRequest,
    ScrapeRunOut,
    SourceCredentialIn,
    SourceCredentialOut,
    SourceCredentialTestIn,
    SourceCredentialTestOut,
    StatsOut,
    TelegramIn,
    TenderChangeOut,
    TenderListResponse,
    TenderOut,
    TokenOut,
    UserOut,
    WatchIn,
    WatchOut,
)
from app.services.aggregator import run_scrape
from app.services.auth import (
    create_access_token,
    get_current_user,
    get_current_user_optional,
    hash_password,
    require_admin,
    verify_password,
)
from app.services.compliance import check_compliance, check_tender_compliance
from app.services.customers import customer_history
from app.services.enrich import enrich_tender
from app.services.export import dashboard_payload, tenders_to_csv, tenders_to_xlsx
from app.services.filters import apply_tender_filters
from app.services.health import source_metrics
from app.services.jobs import enqueue_job
from app.services.monitor import monitor_snapshot, run_monitor_and_alert
from app.services.scoring import score_tender
from app.services.search import fulltext_order_clause
from app.services.source_credentials import (
    API_SOURCES,
    list_credential_status,
    resolve_credentials,
    test_credential_connection,
    upsert_credential,
)

router = APIRouter()

# Light in-memory rate limit for credential writes (per admin user).
_CRED_WRITE_WINDOW_SEC = 60.0
_CRED_WRITE_MAX = 20
_cred_write_hits: dict[int, deque[float]] = defaultdict(deque)


def _rate_limit_cred_writes(user_id: int) -> None:
    now = time.monotonic()
    q = _cred_write_hits[user_id]
    while q and now - q[0] > _CRED_WRITE_WINDOW_SEC:
        q.popleft()
    if len(q) >= _CRED_WRITE_MAX:
        raise HTTPException(status_code=429, detail="Слишком много сохранений, подождите минуту")
    q.append(now)


def _db_label() -> str:
    return "postgresql" if is_postgres() else "sqlite"


def _serialize_tender(
    tender: Tender,
    *,
    profile: CompanyProfile | None = None,
    watch_status: str | None = None,
) -> TenderOut:
    data = TenderOut.model_validate(tender)
    data.relevance = score_tender(tender, profile)
    data.watch_status = watch_status
    return data


@router.get("/health", response_model=HealthOut)
def health() -> HealthOut:
    from sqlalchemy import text

    from app.database import SessionLocal

    db = SessionLocal()
    try:
        db.execute(text("SELECT 1"))
        count = db.query(Tender).count()
        return HealthOut(
            status="ok",
            app=settings.app_name,
            tenders=count,
            database=_db_label(),
            db_ok=True,
        )
    except Exception as exc:  # noqa: BLE001
        try:
            db.rollback()
        except Exception:  # noqa: BLE001
            pass
        return HealthOut(
            status="degraded",
            app=settings.app_name,
            tenders=0,
            database=_db_label(),
            db_ok=False,
            detail=str(exc)[:300],
        )
    finally:
        db.close()


@router.post("/auth/register", response_model=TokenOut)
def register(body: RegisterIn, db: Session = Depends(get_db)) -> TokenOut:
    email = body.email.strip().lower()
    if db.query(User).filter(User.email == email).one_or_none():
        raise HTTPException(status_code=409, detail="Email already registered")
    user = User(email=email, password_hash=hash_password(body.password), name=body.name)
    db.add(user)
    db.flush()
    db.add(CompanyProfile(user_id=user.id, company_name=body.name, okpd_prefixes=[], regions=[], keywords=[]))
    db.commit()
    db.refresh(user)
    return TokenOut(access_token=create_access_token(user.id), user=UserOut.model_validate(user))


@router.post("/auth/login", response_model=TokenOut)
def login(body: LoginIn, db: Session = Depends(get_db)) -> TokenOut:
    user = db.query(User).filter(User.email == body.email.strip().lower()).one_or_none()
    if not user or not verify_password(body.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    return TokenOut(access_token=create_access_token(user.id), user=UserOut.model_validate(user))


@router.get("/auth/me", response_model=UserOut)
def me(user: User = Depends(get_current_user)) -> UserOut:
    return UserOut.model_validate(user)


@router.get("/profile", response_model=ProfileOut)
def get_profile(user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> ProfileOut:
    profile = db.query(CompanyProfile).filter(CompanyProfile.user_id == user.id).one_or_none()
    if not profile:
        profile = CompanyProfile(user_id=user.id)
        db.add(profile)
        db.commit()
        db.refresh(profile)
    return ProfileOut.model_validate(profile)


@router.put("/profile", response_model=ProfileOut)
def update_profile(
    body: ProfileIn,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ProfileOut:
    profile = db.query(CompanyProfile).filter(CompanyProfile.user_id == user.id).one_or_none()
    if not profile:
        profile = CompanyProfile(user_id=user.id)
        db.add(profile)
    profile.company_name = body.company_name
    profile.okpd_prefixes = body.okpd_prefixes
    profile.regions = body.regions
    profile.keywords = body.keywords
    profile.min_price = body.min_price
    profile.max_price = body.max_price
    db.commit()
    db.refresh(profile)
    return ProfileOut.model_validate(profile)


@router.put("/profile/telegram", response_model=UserOut)
def update_telegram(
    body: TelegramIn,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> UserOut:
    user.telegram_chat_id = body.telegram_chat_id
    db.commit()
    db.refresh(user)
    return UserOut.model_validate(user)


@router.get("/sources")
def sources() -> list[dict[str, str]]:
    return list_sources()


@router.get("/niche", response_model=NicheOut)
def niche() -> NicheOut:
    """High-recall / full niche defaults for FE sync."""
    from app.services.niche import niche_payload

    return NicheOut.model_validate(niche_payload())


@router.get("/stats", response_model=StatsOut)
def stats(db: Session = Depends(get_db)) -> StatsOut:
    from app.services.cache import cache_get, cache_set, make_key

    cache_key = make_key("api:stats", _db_label())
    hit = cache_get(cache_key)
    if hit is not None:
        return StatsOut(**hit)

    total = db.query(Tender).filter(Tender.is_duplicate.is_(False)).count()
    active = (
        db.query(Tender)
        .filter(Tender.is_duplicate.is_(False), Tender.status_norm == "accepting")
        .count()
    )
    by_source = {
        row[0]: row[1]
        for row in (
            db.query(Tender.source, func.count(Tender.id))
            .filter(Tender.is_duplicate.is_(False))
            .group_by(Tender.source)
            .all()
        )
    }
    by_law = {
        (row[0] or "—"): row[1]
        for row in (
            db.query(Tender.law, func.count(Tender.id))
            .filter(Tender.is_duplicate.is_(False))
            .group_by(Tender.law)
            .all()
        )
    }
    last = db.query(func.max(ScrapeRun.finished_at)).scalar()
    payload = StatsOut(
        total=total,
        active=active,
        by_source=by_source,
        by_law=by_law,
        last_scrape=last,
        database=_db_label(),
    )
    cache_set(cache_key, payload.model_dump(mode="json"), settings.api_cache_ttl_seconds)
    return payload


@router.get("/dashboard", response_model=DashboardOut)
def dashboard(db: Session = Depends(get_db)) -> DashboardOut:
    return DashboardOut(**dashboard_payload(db))


@router.get("/tenders", response_model=TenderListResponse)
def list_tenders(
    q: str | None = None,
    exclude: str | None = None,
    match_any: bool = True,
    source: str | None = None,
    law: str | None = None,
    region: str | None = None,
    method: str | None = None,
    okpd2: str | None = None,
    status_norm: str | None = None,
    min_price: float | None = None,
    max_price: float | None = None,
    deadline_from: datetime | None = None,
    deadline_to: datetime | None = None,
    hide_outdated: bool | None = None,
    hide_duplicates: bool = True,
    sort: str = Query("published", pattern="^(published|relevance|changed)$"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    user: User | None = Depends(get_current_user_optional),
) -> TenderListResponse:
    from app.services.cache import cache_get, cache_set, make_key

    # Authenticated responses depend on profile/watches — skip shared cache
    cache_key = None
    if user is None:
        raw = "|".join(
            str(x)
            for x in (
                q,
                exclude,
                match_any,
                source,
                law,
                region,
                method,
                okpd2,
                status_norm,
                min_price,
                max_price,
                deadline_from,
                deadline_to,
                hide_outdated,
                hide_duplicates,
                sort,
                page,
                page_size,
            )
        )
        cache_key = make_key("api:tenders", raw)
        hit = cache_get(cache_key)
        if hit is not None:
            return TenderListResponse(**hit)

    query = apply_tender_filters(
        db.query(Tender),
        q=q,
        exclude=exclude,
        match_any=match_any,
        source=source,
        law=law,
        region=region,
        method=method,
        okpd2=okpd2,
        status_norm=status_norm,
        min_price=min_price,
        max_price=max_price,
        deadline_from=deadline_from,
        deadline_to=deadline_to,
        hide_outdated=hide_outdated,
        hide_duplicates=hide_duplicates,
    )

    # Approximate / lighter pagination: for page>1 with approximate_count, avoid COUNT(*)
    if settings.approximate_count and page > 1 and not q and not exclude:
        # Estimate: at least current offset + page; refined if short page
        total = page * page_size  # provisional; adjusted after fetch
        rank_order = fulltext_order_clause(q, match_any=match_any)
        if sort == "changed":
            items = (
                query.order_by(Tender.changed_at.desc(), Tender.id.desc())
                .offset((page - 1) * page_size)
                .limit(page_size + 1)
                .all()
            )
        elif rank_order is not None and sort == "published":
            items = (
                query.order_by(rank_order, Tender.id.desc())
                .offset((page - 1) * page_size)
                .limit(page_size + 1)
                .all()
            )
        else:
            items = (
                query.order_by(Tender.published_at.desc(), Tender.id.desc())
                .offset((page - 1) * page_size)
                .limit(page_size + 1)
                .all()
            )
        has_more = len(items) > page_size
        items = items[:page_size]
        total = (page - 1) * page_size + len(items) + (page_size if has_more else 0)
    else:
        total = query.count()
        rank_order = fulltext_order_clause(q, match_any=match_any)
        if sort == "changed":
            items = (
                query.order_by(Tender.changed_at.desc(), Tender.id.desc())
                .offset((page - 1) * page_size)
                .limit(page_size)
                .all()
            )
        elif rank_order is not None and sort == "published":
            items = query.order_by(rank_order, Tender.id.desc()).offset((page - 1) * page_size).limit(page_size).all()
        else:
            items = (
                query.order_by(Tender.published_at.desc(), Tender.id.desc())
                .offset((page - 1) * page_size)
                .limit(page_size)
                .all()
            )

    profile = None
    watches: dict[int, str] = {}
    if user:
        profile = db.query(CompanyProfile).filter(CompanyProfile.user_id == user.id).one_or_none()
        watch_rows = (
            db.query(TenderWatch)
            .filter(TenderWatch.user_id == user.id, TenderWatch.tender_id.in_([t.id for t in items] or [-1]))
            .all()
        )
        watches = {w.tender_id: w.status for w in watch_rows}

    serialized = [_serialize_tender(t, profile=profile, watch_status=watches.get(t.id)) for t in items]
    if sort == "relevance":
        serialized.sort(key=lambda x: x.relevance or 0, reverse=True)

    resp = TenderListResponse(items=serialized, total=total, page=page, page_size=page_size)
    if cache_key is not None:
        cache_set(cache_key, resp.model_dump(mode="json"), settings.api_cache_ttl_seconds)
    return resp


@router.get("/tenders/export")
def export_tenders(
    format: str = Query("csv", pattern="^(csv|xlsx)$"),
    q: str | None = None,
    exclude: str | None = None,
    match_any: bool = True,
    source: str | None = None,
    law: str | None = None,
    region: str | None = None,
    method: str | None = None,
    okpd2: str | None = None,
    status_norm: str | None = None,
    min_price: float | None = None,
    max_price: float | None = None,
    deadline_from: datetime | None = None,
    deadline_to: datetime | None = None,
    hide_outdated: bool | None = None,
    hide_duplicates: bool = True,
    db: Session = Depends(get_db),
) -> Response:
    query = apply_tender_filters(
        db.query(Tender),
        q=q,
        exclude=exclude,
        match_any=match_any,
        source=source,
        law=law,
        region=region,
        method=method,
        okpd2=okpd2,
        status_norm=status_norm,
        min_price=min_price,
        max_price=max_price,
        deadline_from=deadline_from,
        deadline_to=deadline_to,
        hide_outdated=hide_outdated,
        hide_duplicates=hide_duplicates,
    )
    rows = query.order_by(Tender.published_at.desc()).limit(5000).all()
    if format == "xlsx":
        data = tenders_to_xlsx(rows)
        return Response(
            data,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": "attachment; filename=tenders.xlsx"},
        )
    data = tenders_to_csv(rows)
    return Response(
        data,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": "attachment; filename=tenders.csv"},
    )


@router.get("/tenders/{tender_id}", response_model=TenderOut)
async def get_tender(
    tender_id: int,
    enrich: bool = True,
    force: bool = False,
    db: Session = Depends(get_db),
    user: User | None = Depends(get_current_user_optional),
) -> TenderOut:
    tender = db.get(Tender, tender_id)
    if tender is None:
        raise HTTPException(status_code=404, detail="Tender not found")
    if enrich:
        tender = await enrich_tender(db, tender, force=force)
    profile = None
    watch_status = None
    if user:
        profile = db.query(CompanyProfile).filter(CompanyProfile.user_id == user.id).one_or_none()
        watch = (
            db.query(TenderWatch)
            .filter(TenderWatch.user_id == user.id, TenderWatch.tender_id == tender.id)
            .one_or_none()
        )
        watch_status = watch.status if watch else None
    return _serialize_tender(tender, profile=profile, watch_status=watch_status)


@router.get("/tenders/{tender_id}/changes", response_model=list[TenderChangeOut])
def tender_changes(tender_id: int, db: Session = Depends(get_db)) -> list[TenderChangeOut]:
    rows = (
        db.query(TenderChange)
        .filter(TenderChange.tender_id == tender_id)
        .order_by(TenderChange.id.desc())
        .limit(50)
        .all()
    )
    return [TenderChangeOut.model_validate(r) for r in rows]


@router.get("/tenders/{tender_id}/related", response_model=list[TenderOut])
def related_tenders(
    tender_id: int,
    db: Session = Depends(get_db),
    user: User | None = Depends(get_current_user_optional),
) -> list[TenderOut]:
    tender = db.get(Tender, tender_id)
    if tender is None:
        raise HTTPException(status_code=404, detail="Tender not found")
    rows: list[Tender] = []
    if tender.fingerprint:
        rows = (
            db.query(Tender)
            .filter(Tender.fingerprint == tender.fingerprint, Tender.id != tender.id)
            .order_by(Tender.id.asc())
            .all()
        )
    if tender.duplicate_of_id:
        canonical = db.get(Tender, tender.duplicate_of_id)
        if canonical and canonical not in rows:
            rows.insert(0, canonical)
        extras = (
            db.query(Tender)
            .filter(Tender.duplicate_of_id == tender.duplicate_of_id, Tender.id != tender.id)
            .all()
        )
        for e in extras:
            if e not in rows:
                rows.append(e)
    profile = None
    if user:
        profile = db.query(CompanyProfile).filter(CompanyProfile.user_id == user.id).one_or_none()
    return [_serialize_tender(r, profile=profile) for r in rows]


@router.post("/tenders/{tender_id}/enrich", response_model=TenderOut)
async def enrich_tender_endpoint(
    tender_id: int,
    _user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> TenderOut:
    tender = db.get(Tender, tender_id)
    if tender is None:
        raise HTTPException(status_code=404, detail="Tender not found")
    tender = await enrich_tender(db, tender, force=True)
    return TenderOut.model_validate(tender)


@router.post("/tenders/{tender_id}/watch", response_model=WatchOut)
def upsert_watch(
    tender_id: int,
    body: WatchIn,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> WatchOut:
    if db.get(Tender, tender_id) is None:
        raise HTTPException(status_code=404, detail="Tender not found")
    if body.status not in {"favorite", "in_work", "done"}:
        raise HTTPException(status_code=400, detail="Invalid status")
    watch = (
        db.query(TenderWatch)
        .filter(TenderWatch.user_id == user.id, TenderWatch.tender_id == tender_id)
        .one_or_none()
    )
    if not watch:
        watch = TenderWatch(user_id=user.id, tender_id=tender_id)
        db.add(watch)
    watch.status = body.status
    watch.notes = body.notes
    watch.tags = body.tags
    db.commit()
    db.refresh(watch)
    tender = db.get(Tender, tender_id)
    out = WatchOut.model_validate(watch)
    out.tender = TenderOut.model_validate(tender) if tender else None
    return out


@router.delete("/tenders/{tender_id}/watch")
def delete_watch(
    tender_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, str]:
    watch = (
        db.query(TenderWatch)
        .filter(TenderWatch.user_id == user.id, TenderWatch.tender_id == tender_id)
        .one_or_none()
    )
    if watch:
        db.delete(watch)
        db.commit()
    return {"status": "deleted"}


@router.get("/watches", response_model=list[WatchOut])
def list_watches(user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> list[WatchOut]:
    rows = db.query(TenderWatch).filter(TenderWatch.user_id == user.id).order_by(TenderWatch.updated_at.desc()).all()
    result: list[WatchOut] = []
    for w in rows:
        out = WatchOut.model_validate(w)
        tender = db.get(Tender, w.tender_id)
        out.tender = TenderOut.model_validate(tender) if tender else None
        result.append(out)
    return result


@router.get("/saved-searches", response_model=list[SavedSearchOut])
def list_saved_searches(user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> list[SavedSearchOut]:
    rows = db.query(SavedSearch).filter(SavedSearch.user_id == user.id).order_by(SavedSearch.id.desc()).all()
    return [SavedSearchOut.model_validate(r) for r in rows]


@router.post("/saved-searches", response_model=SavedSearchOut)
def create_saved_search(
    body: SavedSearchIn,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> SavedSearchOut:
    row = SavedSearch(
        user_id=user.id,
        name=body.name,
        filters=body.filters,
        notify_telegram=body.notify_telegram,
        last_seen_ids=[],
        new_count=0,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return SavedSearchOut.model_validate(row)


@router.post("/saved-searches/{search_id}/ack", response_model=SavedSearchOut)
def ack_saved_search(
    search_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> SavedSearchOut:
    row = db.query(SavedSearch).filter(SavedSearch.id == search_id, SavedSearch.user_id == user.id).one_or_none()
    if not row:
        raise HTTPException(status_code=404, detail="Not found")
    row.new_count = 0
    db.commit()
    db.refresh(row)
    return SavedSearchOut.model_validate(row)


@router.delete("/saved-searches/{search_id}")
def delete_saved_search(
    search_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, str]:
    row = db.query(SavedSearch).filter(SavedSearch.id == search_id, SavedSearch.user_id == user.id).one_or_none()
    if row:
        db.delete(row)
        db.commit()
    return {"status": "deleted"}


@router.post("/scrape", response_model=ScrapeEnqueueOut)
async def scrape(
    body: ScrapeRequest | None = None,
    sync: bool = False,
    _admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> ScrapeEnqueueOut:
    sources_req = body.sources if body else None
    if sync or not settings.scrape_via_worker:
        # Release request-scoped session (shared with require_admin) before multi-minute scrape
        try:
            db.close()
        except Exception:  # noqa: BLE001
            pass
        runs = await run_scrape(None, sources_req)
        return ScrapeEnqueueOut(mode="sync", runs=[ScrapeRunOut.model_validate(r) for r in runs])
    job = enqueue_job(db, "scrape", {"sources": sources_req})
    return ScrapeEnqueueOut(mode="queued", job=JobOut.model_validate(job))


@router.get("/jobs/{job_id}", response_model=JobOut)
def get_job(
    job_id: int,
    _user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> JobOut:
    job = db.get(WorkerJob, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return JobOut.model_validate(job)


@router.get("/jobs", response_model=list[JobOut])
def list_jobs(
    limit: int = Query(20, ge=1, le=100),
    _user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[JobOut]:
    rows = db.query(WorkerJob).order_by(WorkerJob.id.desc()).limit(limit).all()
    return [JobOut.model_validate(r) for r in rows]


@router.get("/scrape/runs", response_model=list[ScrapeRunOut])
def scrape_runs(
    limit: int = Query(20, ge=1, le=100),
    _user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[ScrapeRunOut]:
    rows = db.query(ScrapeRun).order_by(ScrapeRun.id.desc()).limit(limit).all()
    return [ScrapeRunOut.model_validate(r) for r in rows]


@router.get("/metrics/sources")
def metrics_sources(db: Session = Depends(get_db)) -> list[dict]:
    from app.services.cache import cache_get, cache_set, make_key

    key = make_key("api:metrics", "sources")
    hit = cache_get(key)
    if hit is not None:
        return hit
    data = source_metrics(db)
    cache_set(key, data, settings.api_cache_ttl_seconds)
    return data


@router.get("/monitor")
async def monitor(
    db: Session = Depends(get_db),
    alert: bool = False,
    user: User | None = Depends(get_current_user_optional),
) -> dict:
    if alert:
        if user is None or not user.is_admin:
            raise HTTPException(status_code=403, detail="Admin required for alerts")
        return await run_monitor_and_alert(db)
    return monitor_snapshot(db)


@router.get("/customers", response_model=list[CustomerOut])
def list_customers(
    q: str | None = None,
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
) -> list[CustomerOut]:
    query = db.query(Customer)
    if q:
        like = f"%{q.strip()}%"
        query = query.filter(
            or_(Customer.name.ilike(like), Customer.inn.ilike(like), Customer.holding_name.ilike(like))
        )
    rows = query.order_by(Customer.tender_count.desc(), Customer.id.desc()).limit(limit).all()
    return [CustomerOut.model_validate(r) for r in rows]


@router.get("/customers/{customer_id}", response_model=CustomerDetailOut)
def get_customer(customer_id: int, db: Session = Depends(get_db)) -> CustomerDetailOut:
    customer = db.get(Customer, customer_id)
    if not customer:
        raise HTTPException(status_code=404, detail="Customer not found")
    history = customer_history(db, customer_id)
    out = CustomerDetailOut.model_validate(customer)
    out.history = [TenderOut.model_validate(t) for t in history]
    return out


@router.post("/compliance/check")
def compliance_check(
    inn: str | None = None,
    name: str | None = None,
    _user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    if not inn and not name:
        raise HTTPException(status_code=400, detail="inn or name required")
    return check_compliance(db, inn, name)


@router.post("/tenders/{tender_id}/compliance")
async def tender_compliance(
    tender_id: int,
    _user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    tender = db.get(Tender, tender_id)
    if tender is None:
        raise HTTPException(status_code=404, detail="Tender not found")
    return await check_tender_compliance(db, tender)


@router.get("/meta/regions")
def regions(db: Session = Depends(get_db)) -> list[str]:
    rows = (
        db.query(Tender.region)
        .filter(Tender.region.isnot(None), Tender.region != "")
        .distinct()
        .order_by(Tender.region)
        .all()
    )
    return [r[0] for r in rows if r[0]]


@router.get("/meta/methods")
def methods(db: Session = Depends(get_db)) -> list[str]:
    rows = (
        db.query(Tender.method)
        .filter(Tender.method.isnot(None), Tender.method != "")
        .distinct()
        .order_by(Tender.method)
        .all()
    )
    return [r[0] for r in rows if r[0]]


@router.get("/presets", response_model=list[FilterPresetOut])
def list_presets(
    db: Session = Depends(get_db),
    user: User | None = Depends(get_current_user_optional),
) -> list[FilterPresetOut]:
    q = db.query(FilterPreset).filter(
        or_(
            FilterPreset.is_builtin.is_(True),
            FilterPreset.is_shared.is_(True),
            FilterPreset.user_id == (user.id if user else -1),
        )
    )
    rows = q.order_by(FilterPreset.is_builtin.desc(), FilterPreset.name).all()
    return [FilterPresetOut.model_validate(r) for r in rows]


@router.post("/presets", response_model=FilterPresetOut)
def create_preset(
    body: FilterPresetIn,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> FilterPresetOut:
    preset = FilterPreset(
        name=body.name,
        description=body.description,
        filters=body.filters,
        is_builtin=False,
        is_shared=body.is_shared,
        user_id=user.id,
    )
    db.add(preset)
    db.commit()
    db.refresh(preset)
    return FilterPresetOut.model_validate(preset)


@router.delete("/presets/{preset_id}")
def delete_preset(
    preset_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, str]:
    preset = db.get(FilterPreset, preset_id)
    if preset is None:
        raise HTTPException(status_code=404, detail="Preset not found")
    if preset.is_builtin:
        raise HTTPException(status_code=400, detail="Builtin presets cannot be deleted")
    if preset.user_id != user.id and not user.is_admin:
        raise HTTPException(status_code=403, detail="Forbidden")
    db.delete(preset)
    db.commit()
    return {"status": "deleted"}


@router.get("/admin/scrape-credentials", response_model=list[SourceCredentialOut])
def get_scrape_credentials(
    _admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> list[SourceCredentialOut]:
    """Masked credential status. Tokens never returned in full."""
    return [SourceCredentialOut.model_validate(row) for row in list_credential_status(db)]


@router.put("/admin/scrape-credentials/{source}", response_model=SourceCredentialOut)
def put_scrape_credential(
    source: str,
    body: SourceCredentialIn,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> SourceCredentialOut:
    if source not in API_SOURCES:
        raise HTTPException(status_code=404, detail="Unknown API source")
    _rate_limit_cred_writes(admin.id)
    try:
        row = upsert_credential(
            db,
            source=source,
            api_url=body.api_url,
            api_token=body.api_token,
            clear_token=body.clear_token,
            user_id=admin.id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return SourceCredentialOut.model_validate(row)


@router.post(
    "/admin/scrape-credentials/{source}/test",
    response_model=SourceCredentialTestOut,
)
async def test_scrape_credential(
    source: str,
    body: SourceCredentialTestIn | None = None,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> SourceCredentialTestOut:
    if source not in API_SOURCES:
        raise HTTPException(status_code=404, detail="Unknown API source")
    _rate_limit_cred_writes(admin.id)

    stored_url, stored_token = resolve_credentials(source, db)
    url = (body.api_url if body and body.api_url is not None else stored_url) or ""
    token = ""
    if body and body.api_token:
        token = body.api_token
    else:
        token = stored_token or ""

    result = await test_credential_connection(url, token)
    return SourceCredentialTestOut.model_validate(result)
