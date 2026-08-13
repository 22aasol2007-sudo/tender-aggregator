"""Telegram chat ingest via Telethon — primary volume source for the hub."""

from __future__ import annotations

import asyncio
import logging
import time
from typing import TYPE_CHECKING

from telethon import TelegramClient, events
from telethon.tl.types import User

from app import config
from app.defaults import DEFAULT_CHATS
from app.ingest import ingest_raw
from app.models import RawLoad

if TYPE_CHECKING:
    from app.db import HubDB

log = logging.getLogger("scraper.telegram")

BACKFILL_PER_CHAT = 80


class TelegramIngest:
    name = "telegram"

    def __init__(self, db: "HubDB") -> None:
        self.db = db
        self.client: TelegramClient | None = None
        self._usernames = {
            c["username"].lower() for c in DEFAULT_CHATS[: config.MAX_TG_CHATS]
        }
        self._ids: set[int] = set()
        self._resolved = 0
        self._failed: list[str] = []
        self._backfill_added = 0
        self._last_error: str | None = None
        self._stopped = False
        self._task: asyncio.Task | None = None
        self._ok = False

    @property
    def ok(self) -> bool:
        return self._ok and self.client is not None and self.client.is_connected()

    async def start(self) -> None:
        """Non-blocking: spawn reconnect supervisor."""
        self._stopped = False
        self._task = asyncio.create_task(self._supervise())

    async def _supervise(self) -> None:
        backoff = 5.0
        while not self._stopped:
            try:
                await self._connect_once()
                backoff = 5.0
                # Stay alive while connected
                while not self._stopped and self.client and self.client.is_connected():
                    await asyncio.sleep(15)
                    await self._save_health(ok=True, note="listening")
                if self._stopped:
                    break
                self._ok = False
                await self._save_health(ok=False, note="disconnected")
            except Exception as exc:
                self._ok = False
                self._last_error = str(exc)
                log.warning("TG supervise: %s — retry in %.0fs", exc, backoff)
                await self._save_health(ok=False, note=f"reconnect: {exc}")
            await self._safe_disconnect()
            if self._stopped:
                break
            await asyncio.sleep(backoff)
            backoff = min(backoff * 1.7, float(config.LISTENER_RETRY_SEC * 5))

    async def _connect_once(self) -> None:
        if not config.API_ID or not config.API_HASH:
            await self._save_health(ok=False, note="missing_api_creds")
            raise RuntimeError("missing_api_creds")
        proxy = config.telethon_proxy()
        kwargs: dict = {
            "session": str(config.SESSION_PATH),
            "api_id": config.API_ID,
            "api_hash": config.API_HASH,
        }
        if proxy:
            from telethon.network import ConnectionTcpMTProxyRandomizedIntermediate

            kwargs["connection"] = ConnectionTcpMTProxyRandomizedIntermediate
            kwargs["proxy"] = proxy
            log.info(
                "TG using MTProxy %s:%s",
                config.TG_PROXY_SERVER,
                config.TG_PROXY_PORT,
            )
        self.client = TelegramClient(**kwargs)
        if config.PHONE:
            await self.client.start(phone=config.PHONE)
        else:
            await self.client.start()
        me = await self.client.get_me()
        log.info("TG logged in as %s", me.username or me.first_name)
        self._resolved = 0
        self._failed = []
        self._ids.clear()
        for u in list(self._usernames):
            try:
                ent = await self.client.get_entity(u)
                self._ids.add(int(ent.id))
                self._resolved += 1
            except Exception as exc:
                self._failed.append(u)
                log.debug("resolve %s: %s", u, exc)
            await asyncio.sleep(0.2)
        self.client.add_event_handler(self.on_message, events.NewMessage)
        log.info(
            "TG watching %s usernames / %s ids (failed resolve %s)",
            len(self._usernames),
            len(self._ids),
            len(self._failed),
        )
        self._ok = True
        await self._save_health(ok=True, note="listening")
        asyncio.create_task(self._backfill())

    async def _safe_disconnect(self) -> None:
        if self.client:
            try:
                await self.client.disconnect()
            except Exception:
                pass
            self.client = None

    async def _save_health(self, *, ok: bool, note: str) -> None:
        await self.db.set_tg_health(
            {
                "ok": ok,
                "note": note,
                "resolved": self._resolved,
                "watched": len(self._usernames),
                "failed_resolve": self._failed[:20],
                "failed_count": len(self._failed),
                "backfill_added": self._backfill_added,
                "last_error": self._last_error,
                "updated_at": time.time(),
            }
        )

    async def _backfill(self) -> None:
        if not self.client:
            return
        added = 0
        self.db.begin_batch()
        try:
            for u in list(self._usernames):
                if self._stopped or not self.client:
                    break
                try:
                    ent = await self.client.get_entity(u)
                    async for msg in self.client.iter_messages(ent, limit=BACKFILL_PER_CHAT):
                        text = (msg.message or "").strip()
                        if len(text) < 20:
                            continue
                        msg_ts = getattr(msg, "date", None)
                        if msg_ts is not None:
                            try:
                                age = time.time() - float(msg_ts.timestamp())
                                if age > config.MAX_LOAD_AGE_SEC:
                                    continue
                            except Exception:
                                pass
                        username = (getattr(ent, "username", None) or u or "").lower()
                        link = f"https://t.me/{username}/{msg.id}" if username else None
                        raw = RawLoad(
                            source="telegram",
                            external_id=f"{username or ent.id}:{msg.id}",
                            title=(getattr(ent, "title", None) or username or "TG"),
                            body=text,
                            url=link,
                            raw={"chat": username, "msg_id": msg.id, "via": "backfill"},
                        )
                        status = await ingest_raw(self.db, raw, min_score=0, scoring="browse")
                        if status == "added":
                            added += 1
                    await asyncio.sleep(0.3)
                except Exception as exc:
                    self._last_error = f"backfill {u}: {exc}"
                    log.debug("%s", self._last_error)
        finally:
            await self.db.end_batch()
        self._backfill_added = added
        log.info("TG backfill done, added=%s", added)
        await self._save_health(ok=True, note="backfill_done")

    async def stop(self) -> None:
        self._stopped = True
        await self._safe_disconnect()
        if self._task:
            self._task.cancel()

    async def on_message(self, event: events.NewMessage.Event) -> None:
        chat = await event.get_chat()
        if isinstance(chat, User):
            return
        username = (getattr(chat, "username", None) or "").lower()
        chat_id = int(getattr(chat, "id", 0) or 0)
        if username not in self._usernames and chat_id not in self._ids:
            return
        text = (event.raw_text or "").strip()
        if len(text) < 20:
            return
        link = f"https://t.me/{username}/{event.id}" if username else None
        raw = RawLoad(
            source="telegram",
            external_id=f"{username or chat_id}:{event.id}",
            title=(getattr(chat, "title", None) or username or "TG"),
            body=text,
            url=link,
            raw={"chat": username, "msg_id": event.id},
        )
        try:
            await ingest_raw(self.db, raw, min_score=0, scoring="browse")
            await self._save_health(ok=True, note="listening")
        except Exception as exc:
            self._last_error = str(exc)
            log.warning("tg ingest: %s", exc)
            await self._save_health(ok=True, note="ingest_error")
