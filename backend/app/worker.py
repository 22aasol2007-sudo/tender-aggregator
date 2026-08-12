from __future__ import annotations

import argparse
import asyncio
import logging
from datetime import datetime, timezone

from app.config import settings
from app.database import SessionLocal, init_db
from app.models import Tender, WorkerJob
from app.services.aggregator import run_scrape
from app.services.contracts import run_contract_scrape
from app.services.enrich import enrich_tender
from app.services.http_client import close_client
from app.services.jobs import claim_next_job, finish_job
from app.services.monitor import run_monitor_and_alert

logger = logging.getLogger("tender.worker")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

MODE_TYPES = {
    "all": None,
    "scrape": ["scrape", "monitor", "contracts"],
    "enrich": ["enrich"],
}


def _finish_job_safe(job_id: int, *, result: dict | None = None, error: str | None = None) -> None:
    db = SessionLocal()
    try:
        job = db.get(WorkerJob, job_id)
        if job is None:
            return
        finish_job(db, job, result=result, error=error)
    finally:
        db.close()


async def process_one(allowed_types: list[str] | None = None) -> bool:
    db = SessionLocal()
    try:
        job = claim_next_job(db, allowed_types)
        if not job:
            return False
        job_id = job.id
        job_type = job.job_type
        payload = job.payload or {}
        logger.info("Job %s type=%s priority=%s", job_id, job_type, getattr(job, "priority", "?"))
    finally:
        db.close()

    try:
        if job_type == "scrape":
            sources = payload.get("sources")
            runs = await asyncio.wait_for(
                run_scrape(None, sources),
                timeout=settings.scrape_job_timeout_seconds,
            )
            _finish_job_safe(
                job_id,
                result={
                    "runs": [
                        {
                            "source": r.source,
                            "status": r.status,
                            "fetched": r.fetched,
                            "upserted": r.upserted,
                            "skipped": r.skipped,
                        }
                        for r in runs
                    ],
                    "finished_at": datetime.now(timezone.utc).isoformat(),
                },
            )
        elif job_type == "enrich":
            db = SessionLocal()
            try:
                job = db.get(WorkerJob, job_id)
                if job is None:
                    return True
                ids = list(payload.get("tender_ids") or [])
                done = 0
                for tid in ids:
                    tender = db.get(Tender, tid)
                    if not tender or not str(tender.source).startswith("zakupki"):
                        continue
                    try:
                        await enrich_tender(db, tender, force=False)
                        done += 1
                    except Exception as exc:  # noqa: BLE001
                        logger.warning("Enrich %s failed: %s", tid, exc)
                finish_job(db, job, result={"enriched": done, "requested": len(ids)})
            finally:
                db.close()
        elif job_type == "contracts":
            search_string = payload.get("search_string")
            runs = await asyncio.wait_for(
                run_contract_scrape(None, search_string=search_string),
                timeout=settings.scrape_job_timeout_seconds,
            )
            _finish_job_safe(
                job_id,
                result={
                    "runs": [
                        {
                            "source": r.source,
                            "status": r.status,
                            "fetched": r.fetched,
                            "upserted": r.upserted,
                            "skipped": r.skipped,
                            "error": r.error,
                        }
                        for r in runs
                    ],
                    "finished_at": datetime.now(timezone.utc).isoformat(),
                },
            )
        elif job_type == "monitor":
            db = SessionLocal()
            try:
                job = db.get(WorkerJob, job_id)
                if job is None:
                    return True
                snap = await run_monitor_and_alert(db)
                finish_job(
                    db,
                    job,
                    result={"alerts": snap.get("alerts", []), "unhealthy": snap.get("unhealthy_count")},
                )
            finally:
                db.close()
        else:
            _finish_job_safe(job_id, error=f"Unknown job type: {job_type}")
    except TimeoutError:
        logger.exception("Job %s timed out", job_id)
        _finish_job_safe(job_id, error=f"timeout after {settings.scrape_job_timeout_seconds}s")
    except Exception as exc:  # noqa: BLE001
        logger.exception("Job %s failed", job_id)
        _finish_job_safe(job_id, error=str(exc))
    return True


async def main(poll_seconds: float = 2.0, mode: str = "all") -> None:
    init_db()
    allowed = MODE_TYPES.get(mode, None)
    logger.info("Worker started mode=%s, polling every %ss", mode, poll_seconds)
    try:
        while True:
            worked = await process_one(allowed)
            if not worked:
                await asyncio.sleep(poll_seconds)
    finally:
        await close_client()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Tender aggregator worker")
    parser.add_argument(
        "--mode",
        choices=["all", "scrape", "enrich"],
        default="all",
        help="Job types to process: all | scrape (+monitor) | enrich",
    )
    parser.add_argument("--poll", type=float, default=2.0, help="Idle poll interval seconds")
    args = parser.parse_args()
    asyncio.run(main(poll_seconds=args.poll, mode=args.mode))
