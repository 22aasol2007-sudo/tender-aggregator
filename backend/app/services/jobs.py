from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.models import WorkerJob

# Lower number = higher priority
JOB_PRIORITIES = {
    "scrape": 50,
    "monitor": 100,
    "enrich": 200,
}


def enqueue_job(
    db: Session,
    job_type: str,
    payload: dict | None = None,
    *,
    priority: int | None = None,
) -> WorkerJob:
    # Avoid duplicate pending scrapes with same payload sources
    if job_type == "scrape":
        pending = (
            db.query(WorkerJob)
            .filter(WorkerJob.job_type == "scrape", WorkerJob.status == "pending")
            .order_by(WorkerJob.id.desc())
            .first()
        )
        if pending:
            return pending
    if job_type == "enrich":
        # Merge into pending enrich if exists
        pending = (
            db.query(WorkerJob)
            .filter(WorkerJob.job_type == "enrich", WorkerJob.status == "pending")
            .order_by(WorkerJob.id.desc())
            .first()
        )
        if pending:
            existing_ids = list((pending.payload or {}).get("tender_ids") or [])
            incoming = list((payload or {}).get("tender_ids") or [])
            merged = list(dict.fromkeys(existing_ids + incoming))[:50]
            pending.payload = {**(pending.payload or {}), "tender_ids": merged}
            db.commit()
            db.refresh(pending)
            return pending

    job = WorkerJob(
        job_type=job_type,
        payload=payload or {},
        status="pending",
        priority=priority if priority is not None else JOB_PRIORITIES.get(job_type, 100),
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    return job


def claim_next_job(db: Session, allowed_types: list[str] | None = None) -> WorkerJob | None:
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
