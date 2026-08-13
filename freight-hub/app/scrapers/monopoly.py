"""Monopoly.Online — partner API only; public load feed is not open."""

from __future__ import annotations

import logging

from app.models import RawLoad

log = logging.getLogger("scraper.monopoly")


class MonopolyScraper:
    """
    Monopoly.Online / cargo-search.monopoly.ru require authorized partner API
    (api.monopoly.online). Public HTML is a landing/Tilda page without a free
    loads feed. Set MONOPOLY_API_TOKEN later to wire official client.
    """

    name = "monopoly"

    def __init__(self, token: str | None = None) -> None:
        self.token = (token or "").strip()

    async def fetch(self) -> list[RawLoad]:
        if not self.token:
            log.info(
                "monopoly skipped — нет публичной ленты грузов; нужен партнёрский API token"
            )
            return []
        log.warning("monopoly token set but official cargo client not wired yet")
        return []
