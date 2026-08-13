"""Background scrape worker — parallel, per-source intervals."""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from typing import Any

from app import config
from app.db import HubDB
from app.scrapers import run_scraper
from app.scrapers.ati import AtiScraper
from app.scrapers.avtodispetcher import AvtodispetcherScraper
from app.scrapers.cargocash import CargoCashScraper
from app.scrapers.ingruz import InGruzScraper
from app.scrapers.monopoly import MonopolyScraper
from app.scrapers.papacargo import PapaCargoScraper
from app.scrapers.perevozka24 import DEFAULT_PATHS, Perevozka24Scraper
from app.scrapers.roolz import RoolzScraper
from app.scrapers.tg_public import TgPublicScraper
from app.scrapers.vezetvsem import VezetVsemScraper

log = logging.getLogger("worker")


@dataclass
class ScraperSlot:
    scraper: Any
    interval_sec: float
    last_run: float = 0.0
    enabled: bool = True


class ScrapeWorker:
    def __init__(self, db: HubDB) -> None:
        self.db = db
        self._task: asyncio.Task | None = None
        self._manual_task: asyncio.Task | None = None
        self._sem = asyncio.Semaphore(config.SCRAPE_CONCURRENCY)
        self._manual_running = False
        self._last_manual: dict[str, Any] = {"running": False, "results": [], "started_at": 0, "finished_at": 0}
        ati_token = getattr(config, "ATI_API_TOKEN", "") or ""
        mono_token = getattr(config, "MONOPOLY_API_TOKEN", "") or ""
        # Hot sources: frequent. Cold / empty: rare or off until token.
        self.slots: list[ScraperSlot] = [
            ScraperSlot(PapaCargoScraper(pages=5), 300),
            ScraperSlot(Perevozka24Scraper(), 90),
            ScraperSlot(CargoCashScraper(list_pages=25), 120),
            ScraperSlot(VezetVsemScraper(max_pages=10), 120),
            ScraperSlot(AvtodispetcherScraper(max_pages=8), 300),
            ScraperSlot(TgPublicScraper(), 180),
            ScraperSlot(RoolzScraper(), 600),
            ScraperSlot(InGruzScraper(), 900, enabled=False),  # nearly empty board
            ScraperSlot(MonopolyScraper(token=mono_token), 600, enabled=bool(mono_token)),
            ScraperSlot(AtiScraper(token=ati_token), 600, enabled=bool(ati_token)),
        ]

    def start(self) -> None:
        self._task = asyncio.create_task(self._loop())

    async def stop(self) -> None:
        if self._manual_task and not self._manual_task.done():
            self._manual_task.cancel()
        if self._task:
            self._task.cancel()

    def manual_status(self) -> dict[str, Any]:
        return dict(self._last_manual)

    async def _run_one(self, slot: ScraperSlot) -> dict:
        async with self._sem:
            log.info("scrape %s …", slot.scraper.name)
            return await run_scraper(self.db, slot.scraper)

    async def _run_scrapers(self, scrapers: list[Any], *, cleanup: bool = True) -> list[dict]:
        sem = asyncio.Semaphore(max(config.SCRAPE_CONCURRENCY, 6))

        async def _one(scraper: Any) -> dict:
            async with sem:
                log.info("scrape %s …", scraper.name)
                return await run_scraper(self.db, scraper)

        results = await asyncio.gather(*[_one(s) for s in scrapers], return_exceptions=True)
        out: list[dict] = []
        for scraper, res in zip(scrapers, results):
            if isinstance(res, Exception):
                log.exception("scrape %s failed: %s", scraper.name, res)
                out.append({"source": scraper.name, "ok": False, "error": str(res)})
            else:
                out.append(res)
        if cleanup:
            await self.db.cleanup_smart()
        return out

    async def run_due(self, *, force_all: bool = False) -> list[dict]:
        now = time.time()
        due = [
            s
            for s in self.slots
            if s.enabled and (force_all or now - s.last_run >= s.interval_sec)
        ]
        if not due:
            return []
        results = await asyncio.gather(
            *[self._run_one(s) for s in due],
            return_exceptions=True,
        )
        out: list[dict] = []
        for slot, res in zip(due, results):
            slot.last_run = time.time()
            if isinstance(res, Exception):
                log.exception("scrape %s failed: %s", slot.scraper.name, res)
                out.append({"source": slot.scraper.name, "ok": False, "error": str(res)})
            else:
                out.append(res)
        await self.db.cleanup_smart()
        return out

    def _quick_scrapers(self) -> list[Any]:
        # Lightweight pass for the UI button — hot boards only, few pages.
        p24_paths = list(DEFAULT_PATHS)[:6]
        return [
            PapaCargoScraper(pages=2),
            Perevozka24Scraper(paths=p24_paths),
            CargoCashScraper(list_pages=3),
            VezetVsemScraper(max_pages=2),
        ]

    async def run_once(self) -> list[dict]:
        """Full scrape of all enabled sources (background worker / admin)."""
        return await self.run_due(force_all=True)

    async def run_manual_quick(self) -> list[dict]:
        return await self._run_scrapers(self._quick_scrapers(), cleanup=True)

    def start_manual(self, *, quick: bool = True) -> dict[str, Any]:
        """Fire-and-forget manual refresh; returns immediately."""
        if self._manual_running:
            return {"started": False, "busy": True, **self.manual_status()}

        async def _job() -> None:
            self._manual_running = True
            started = time.time()
            self._last_manual = {
                "running": True,
                "quick": quick,
                "results": [],
                "started_at": started,
                "finished_at": 0,
            }
            try:
                results = await (self.run_manual_quick() if quick else self.run_once())
                # Mark slots so background loop doesn't immediately re-hit same boards
                now = time.time()
                done_names = {r.get("source") for r in results if r.get("ok")}
                for slot in self.slots:
                    if slot.scraper.name in done_names:
                        slot.last_run = now
                self._last_manual = {
                    "running": False,
                    "quick": quick,
                    "results": results,
                    "started_at": started,
                    "finished_at": time.time(),
                }
            except Exception as exc:
                log.exception("manual scrape: %s", exc)
                self._last_manual = {
                    "running": False,
                    "quick": quick,
                    "results": [{"ok": False, "error": str(exc)}],
                    "started_at": started,
                    "finished_at": time.time(),
                }
            finally:
                self._manual_running = False

        self._manual_task = asyncio.create_task(_job())
        return {"started": True, "busy": False, "quick": quick, "running": True}

    async def _loop(self) -> None:
        await asyncio.sleep(2)
        while True:
            try:
                if not self._manual_running:
                    await self.run_due(force_all=False)
            except Exception as exc:
                log.exception("scrape loop: %s", exc)
            await asyncio.sleep(config.SCRAPE_TICK_SEC)
