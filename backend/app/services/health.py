from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.models import ScrapeRun, SourceHealth
from app.parsers import get_parsers, list_sources


def ensure_source_rows(db: Session) -> None:
    names = {s["id"]: s["name"] for s in list_sources()}
    for source_id, name in names.items():
        row = db.query(SourceHealth).filter(SourceHealth.source == source_id).one_or_none()
        if row is None:
            db.add(SourceHealth(source=source_id, display_name=name, last_status="unknown"))
        elif not row.display_name:
            row.display_name = name
    db.commit()


def record_source_run(db: Session, run: ScrapeRun) -> SourceHealth:
    ensure_source_rows(db)
    row = db.query(SourceHealth).filter(SourceHealth.source == run.source).one_or_none()
    if row is None:
        row = SourceHealth(source=run.source)
        db.add(row)

    if run.status == "skipped":
        # Do not bump last_run_at so half-open re-probe can fire later
        row.last_status = run.status
        row.last_error = run.error
        db.commit()
        db.refresh(row)
        return row

    now = datetime.now(timezone.utc)
    row.last_run_at = now
    row.last_status = run.status
    row.last_error = run.error
    row.last_fetched = run.fetched or 0
    row.last_upserted = run.upserted or 0

    if run.status == "ok":
        row.success_count = (row.success_count or 0) + 1
        row.last_ok_at = now
        row.consecutive_failures = 0
    elif run.status == "empty":
        row.empty_count = (row.empty_count or 0) + 1
        parser = get_parsers().get(run.source)
        # Known SPA/login sources: record empty truthfully but don't fail-fast lock
        if parser is not None and not getattr(parser, "public_listing", True):
            row.consecutive_failures = 0
        else:
            row.consecutive_failures = (row.consecutive_failures or 0) + 1
    elif run.status == "needs_api":
        # Credentials gap — not a transport error; don't inflate error_count / fail-fast
        row.empty_count = (row.empty_count or 0) + 1
        row.consecutive_failures = 0
    elif run.status == "fallback":
        row.fallback_count = (row.fallback_count or 0) + 1
        row.consecutive_failures = (row.consecutive_failures or 0) + 1
        if run.error and "пуст" in (run.error or "").lower():
            row.empty_count = (row.empty_count or 0) + 1
    else:
        row.error_count = (row.error_count or 0) + 1
        row.consecutive_failures = (row.consecutive_failures or 0) + 1

    db.commit()
    db.refresh(row)
    return row


def source_metrics(db: Session) -> list[dict]:
    ensure_source_rows(db)
    rows = db.query(SourceHealth).order_by(SourceHealth.source).all()
    out = []
    for row in rows:
        total = (row.success_count or 0) + (row.fallback_count or 0) + (row.error_count or 0) + (row.empty_count or 0)
        success_rate = round(100.0 * (row.success_count or 0) / total, 1) if total else 0.0
        out.append(
            {
                "source": row.source,
                "display_name": row.display_name or row.source,
                "last_status": row.last_status,
                "last_ok_at": row.last_ok_at,
                "last_run_at": row.last_run_at,
                "last_error": row.last_error,
                "success_count": row.success_count,
                "fallback_count": row.fallback_count,
                "error_count": row.error_count,
                "empty_count": row.empty_count,
                "consecutive_failures": row.consecutive_failures,
                "success_rate": success_rate,
                "last_fetched": row.last_fetched,
                "last_upserted": row.last_upserted,
            }
        )
    return out


def recent_runs_by_source(db: Session, limit: int = 5) -> dict[str, list[dict]]:
    result: dict[str, list[dict]] = {}
    for source_id in get_parsers().keys():
        runs = (
            db.query(ScrapeRun)
            .filter(ScrapeRun.source == source_id)
            .order_by(ScrapeRun.id.desc())
            .limit(limit)
            .all()
        )
        result[source_id] = [
            {
                "id": r.id,
                "status": r.status,
                "fetched": r.fetched,
                "upserted": r.upserted,
                "skipped": r.skipped,
                "error": r.error,
                "finished_at": r.finished_at,
            }
            for r in runs
        ]
    return result
