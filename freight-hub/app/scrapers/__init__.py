"""Re-export + batch wrapper for site scrapers."""

from __future__ import annotations

from typing import Protocol

from app.db import HubDB
from app.models import RawLoad


class Scraper(Protocol):
    name: str

    async def fetch(self) -> list[RawLoad]:
        ...


async def run_scraper(db: HubDB, scraper: Scraper) -> dict:
    import time

    from app.ingest import ingest_raw

    started = time.time()
    added = updated = skipped = 0
    err = None
    try:
        items = await scraper.fetch()
        db.begin_batch()
        try:
            for raw in items:
                status = await ingest_raw(db, raw)
                if status == "added":
                    added += 1
                elif status == "updated":
                    updated += 1
                elif status == "skipped":
                    skipped += 1
        finally:
            await db.end_batch()
        await db.log_run(scraper.name, True, added, updated, None, started)
        return {
            "source": scraper.name,
            "ok": True,
            "added": added,
            "updated": updated,
            "skipped": skipped,
            "total": len(items),
        }
    except Exception as exc:
        err = str(exc)[:500]
        try:
            await db.end_batch()
        except Exception:
            pass
        await db.log_run(scraper.name, False, added, updated, err, started)
        return {
            "source": scraper.name,
            "ok": False,
            "error": err,
            "added": added,
            "updated": updated,
            "skipped": skipped,
        }
