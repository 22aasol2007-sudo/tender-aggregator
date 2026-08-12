from __future__ import annotations

from datetime import datetime, timedelta, timezone

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.config import settings
from app.database import SessionLocal
from app.parsers import get_parsers
from app.services.aggregator import run_scrape
from app.services.jobs import enqueue_job
from app.services.monitor import run_monitor_and_alert


scheduler = AsyncIOScheduler()

# Fast path: EIS + live commercial ETPs
HOT_SOURCES: tuple[str, ...] = (
    "zakupki_44",
    "zakupki_223",
    "b2b_center",
    "fabrikant",
    "otc",
    "rostender",
)


def _cold_sources() -> list[str]:
    hot = set(HOT_SOURCES)
    return [sid for sid in get_parsers() if sid not in hot]


async def _enqueue_or_run(sources: list[str] | None, job_timeout: float | None = None) -> None:
    import asyncio

    if settings.scrape_via_worker:
        db = SessionLocal()
        try:
            payload: dict = {}
            if sources is not None:
                payload["sources"] = sources
            enqueue_job(db, "scrape", payload)
        finally:
            db.close()
        return
    timeout = job_timeout if job_timeout is not None else float(settings.scrape_job_timeout_seconds)
    try:
        await asyncio.wait_for(run_scrape(None, sources), timeout=timeout)
    except TimeoutError:
        pass


async def _scheduled_scrape_hot() -> None:
    await _enqueue_or_run(list(HOT_SOURCES), job_timeout=float(settings.scrape_job_timeout_seconds))


async def _scheduled_scrape_cold() -> None:
    await _enqueue_or_run(_cold_sources(), job_timeout=float(settings.scrape_job_timeout_seconds))


async def _scheduled_scrape() -> None:
    """Legacy full scrape (kept for startup one-shot)."""
    await _enqueue_or_run(None)


async def _scheduled_monitor() -> None:
    db = SessionLocal()
    try:
        if settings.scrape_via_worker:
            enqueue_job(db, "monitor", {})
        else:
            await run_monitor_and_alert(db)
    finally:
        db.close()


async def _scheduled_contracts() -> None:
    import asyncio

    if settings.scrape_via_worker:
        db = SessionLocal()
        try:
            enqueue_job(db, "contracts", {})
        finally:
            db.close()
        return
    try:
        from app.services.contracts import run_contract_scrape

        await asyncio.wait_for(
            run_contract_scrape(None),
            timeout=float(settings.scrape_job_timeout_seconds),
        )
    except TimeoutError:
        pass


def start_scheduler() -> None:
    if scheduler.running:
        return
    hot_min = max(1.0, float(settings.hot_scrape_interval_minutes))
    cold_min = max(5, int(settings.cold_scrape_interval_minutes))
    contracts_min = max(15, int(settings.contracts_scrape_interval_minutes))
    scheduler.add_job(
        _scheduled_scrape_hot,
        "interval",
        minutes=hot_min,
        id="scrape_hot",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
        misfire_grace_time=90,
    )
    scheduler.add_job(
        _scheduled_scrape_cold,
        "interval",
        minutes=cold_min,
        id="scrape_cold",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
        misfire_grace_time=180,
    )
    scheduler.add_job(
        _scheduled_contracts,
        "interval",
        minutes=contracts_min,
        id="scrape_contracts",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
        misfire_grace_time=180,
    )
    # Backward-compatible id for operators; full scrape less often than hot
    scheduler.add_job(
        _scheduled_scrape,
        "interval",
        minutes=max(cold_min, settings.scrape_interval_minutes),
        id="scrape_all",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
        misfire_grace_time=120,
    )
    # One-shot shortly after boot: hot first, then cold, then contracts
    scheduler.add_job(
        _scheduled_scrape_hot,
        "date",
        run_date=datetime.now(timezone.utc) + timedelta(seconds=20),
        id="scrape_hot_startup",
        replace_existing=True,
        max_instances=1,
    )
    scheduler.add_job(
        _scheduled_scrape_cold,
        "date",
        run_date=datetime.now(timezone.utc) + timedelta(seconds=45),
        id="scrape_cold_startup",
        replace_existing=True,
        max_instances=1,
    )
    scheduler.add_job(
        _scheduled_contracts,
        "date",
        run_date=datetime.now(timezone.utc) + timedelta(seconds=70),
        id="scrape_contracts_startup",
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
