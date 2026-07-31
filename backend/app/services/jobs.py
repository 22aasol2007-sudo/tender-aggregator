from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.database import is_postgres
from app.models import WorkerJob

# Lower number = higher priority
JOB_PRIORITIES = {
    "scrape": 50,
    "monitor": 100,
    "enrich": 200,
}


def _sources_key(payload: dict | None) -> str:
    sources = (payload or {}).get("sources")
    if not sources:
        return "*"
    return ",".join(sorted(str(s) for s in sources))


def enqueue_job(
    db: Session,
    job_type: str,
    payload: dict | None = None,
    *,
    priority: int | None = None,
) -> WorkerJob:
    payload = payload or {}
    # Avoid duplicate pending scrapes with the same sources set
    if job_type == "scrape":
        key = _sources_key(payload)
        pending_rows = (
            db.query(WorkerJob)
            .filter(WorkerJob.job_type == "scrape", WorkerJob.status == "pending")
            .order_by(WorkerJob.id.desc())
            .all()
        )
        for pending in pending_rows:
            if _sources_key(pending.payload) == key:
                return pending
    if job_type == "enrich":
        pending = (
            db.query(WorkerJob)
            .filter(WorkerJob.job_type == "enrich", WorkerJob.status == "pending")
            .order_by(WorkerJob.id.desc())
            .first()
        )
        if pending:
            existing_ids = list((pending.payload or {}).get("tender_ids") or [])
            incoming = list(payload.get("tender_ids") or [])
            merged = list(dict.fromkeys(existing_ids + incoming))[:50]
            pending.payload = {**(pending.payload or {}), "tender_ids": merged}
            db.commit()
            db.refresh(pending)
            return pending

    job = WorkerJob(
        job_type=job_type,
        payload=payload,
        status="pending",
        priority=priority if priority is not None else JOB_PRIORITIES.get(job_type, 100),
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    return job


def claim_next_job(db: Session, allowed_types: list[str] | None = None) -> WorkerJob | None:
    if is_postgres():
        type_clause = ""
        params: dict = {}
        if allowed_types:
            type_clause = " AND job_type = ANY(:types)"
            params["types"] = allowed_types
        row = db.execute(
            text(
                f"""
                SELECT id FROM worker_jobs
                WHERE status = 'pending'{type_clause}
                ORDER BY priority ASC, id ASC
                FOR UPDATE SKIP LOCKED
                LIMIT 1
                """
            ),
            params,
        ).first()
        if not row:
            return None
        job = db.get(WorkerJob, row[0])
    else:
        q = db.query(WorkerJob).filter(WorkerJob.status == "pending")
        if allowed_types:
            q = q.filter(WorkerJob.job_type.in_(allowed_types))
        job = q.order_by(WorkerJob.priority.asc(), WorkerJob.id.asc()).first()
        if not job:
            return None

    job.status = "running"
    job.started_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(job)
    return job


def finish_job(db: Session, job: WorkerJob, *, result: dict | None = None, error: str | None = None) -> None:
    job.finished_at = datetime.now(timezone.utc)
    if error:
        job.status = "failed"
        job.error = error[:2000]
    else:
        job.status = "done"
        job.result = result or {}
        job.error = None
    db.commit()
