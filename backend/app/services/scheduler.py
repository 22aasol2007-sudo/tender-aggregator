from __future__ import annotations

from datetime import datetime, timedelta, timezone

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.config import settings
from app.database import SessionLocal
from app.services.aggregator import run_scrape
from app.services.jobs import enqueue_job
from app.services.monitor import run_monitor_and_alert


scheduler = AsyncIOScheduler()


async def _scheduled_scrape() -> None:
    import asyncio

    if settings.scrape_via_worker:
        db = SessionLocal()
        try:
            enqueue_job(db, "scrape", {})
        finally:
            db.close()
        return
    try:
        # Hard ceiling so a stuck RU host can't block the interval forever.
        # run_scrape manages its own short-lived sessions (no parent held across I/O).
        await asyncio.wait_for(
            run_scrape(None),
            timeout=float(settings.scrape_job_timeout_seconds),
        )
    except TimeoutError:
        # Logged by uvicorn; next interval will retry
        pass


async def _scheduled_monitor() -> None:
    db = SessionLocal()
    try:
        if settings.scrape_via_worker:
            enqueue_job(db, "monitor", {})
        else:
            await run_monitor_and_alert(db)
    finally:
        db.close()


def start_scheduler() -> None:
    if scheduler.running:
        return
    scheduler.add_job(
        _scheduled_scrape,
        "interval",
        minutes=settings.scrape_interval_minutes,
        id="scrape_all",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
        misfire_grace_time=120,
    )
    # One-shot shortly after boot so fail-fast reset takes effect immediately
    scheduler.add_job(
        _scheduled_scrape,
        "date",
        run_date=datetime.now(timezone.utc) + timedelta(seconds=20),
        id="scrape_all_startup",
        replace_existing=True,
        max_instances=1,
    )
    scheduler.add_job(
        _scheduled_monitor,
        "interval",
        minutes=max(5, settings.source_silence_minutes // 2),
        id="monitor_sources",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
        misfire_grace_time=120,
    )
    scheduler.start()


def stop_scheduler() -> None:
    if scheduler.running:
        scheduler.shutdown(wait=False)
