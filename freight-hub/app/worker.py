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
from app.scrapers.perevozka24 import Perevozka24Scraper
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
        self._sem = asyncio.Semaphore(config.SCRAPE_CONCURRENCY)
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
        if self._task:
            self._task.cancel()

    async def _run_one(self, slot: ScraperSlot) -> dict:
        async with self._sem:
            log.info("scrape %s …", slot.scraper.name)
            return await run_scraper(self.db, slot.scraper)

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

    async def run_once(self) -> list[dict]:
        """Manual / API: scrape all enabled sources once."""
        return await self.run_due(force_all=True)

    async def _loop(self) -> None:
        await asyncio.sleep(2)
        while True:
            try:
                await self.run_due(force_all=False)
            except Exception as exc:
                log.exception("scrape loop: %s", exc)
            await asyncio.sleep(config.SCRAPE_TICK_SEC)
