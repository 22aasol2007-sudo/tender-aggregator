"""Scrape public Telegram channel previews via https://t.me/s/<channel> (no login)."""

from __future__ import annotations

import logging
import re
from html import unescape

import httpx

from app import config
from app.defaults import PUBLIC_TG_CHANNELS
from app.models import RawLoad

log = logging.getLogger("scraper.tg_public")

_MSG_RE = re.compile(
    r'data-post="(?P<chan>[^"/]+)/(?P<mid>\d+)"[^>]*>.*?'
    r'class="tgme_widget_message_text[^"]*"[^>]*>(?P<body>.*?)</div>',
    re.S,
)
_TAG_RE = re.compile(r"<[^>]+>")


def _html_to_text(html: str) -> str:
    t = html.replace("<br>", "\n").replace("<br/>", "\n").replace("<br />", "\n")
    t = _TAG_RE.sub(" ", t)
    t = unescape(t)
    return re.sub(r"[ \t]+", " ", t).strip()


class TgPublicScraper:
    name = "tg_public"

    def __init__(self, channels: list[str] | None = None) -> None:
        self.channels = channels or PUBLIC_TG_CHANNELS

    async def fetch(self) -> list[RawLoad]:
        out: list[RawLoad] = []
        headers = {
            "User-Agent": config.USER_AGENT,
            "Accept": "text/html,application/xhtml+xml",
            "Accept-Language": "ru,en;q=0.8",
            "Accept-Encoding": "identity",
        }
        async with httpx.AsyncClient(timeout=25.0, headers=headers, follow_redirects=True) as client:
            for chan in self.channels:
                try:
                    r = await client.get(f"https://t.me/s/{chan}")
                    if r.status_code != 200:
                        log.warning("tg_public %s status %s", chan, r.status_code)
                        continue
                    out.extend(self._parse(r.text, chan))
                except Exception as exc:
                    log.warning("tg_public %s: %s", chan, exc)
        log.info("tg_public fetched %s", len(out))
        return out

    def _parse(self, html: str, chan: str) -> list[RawLoad]:
        out: list[RawLoad] = []
        seen: set[str] = set()
        for m in _MSG_RE.finditer(html):
            mid = m.group("mid")
            eid = f"{chan}:{mid}"
            if eid in seen:
                continue
            seen.add(eid)
            body = _html_to_text(m.group("body"))
            if len(body) < 25:
                continue
            out.append(
                RawLoad(
                    source="tg_public",
                    external_id=eid,
                    title=f"@{chan}",
                    body=body[:4000],
                    url=f"https://t.me/{chan}/{mid}",
                    raw={"channel": chan, "msg_id": mid, "via": "tme_s"},
                )
            )
        return out
