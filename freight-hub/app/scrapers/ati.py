"""ATI.SU — only with legal API/token. Stub until credentials are provided."""

from __future__ import annotations

import logging

from app.models import RawLoad

log = logging.getLogger("scraper.ati")


class AtiScraper:
    """Placeholder: ATI public loads require authorized API access."""

    name = "ati"

    def __init__(self, token: str | None = None) -> None:
        self.token = (token or "").strip()

    async def fetch(self) -> list[RawLoad]:
        if not self.token:
            log.info("ati skipped — set ATI_API_TOKEN for legal API access")
            return []
        # Token path reserved for official ATI API client when available.
        log.warning("ati token set but official client not wired yet")
        return []
