"""Telegram chat ingest via Telethon — primary volume source for the hub."""

from __future__ import annotations

import asyncio
import logging
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any

from telethon import TelegramClient, events, utils
from telethon.tl.types import User
import hashlib

from app import config
from app.defaults import DEFAULT_CHATS
from app.ingest import ingest_raw
from app.ingest_metrics import record
from app.models import RawLoad

if TYPE_CHECKING:
    from app.db import HubDB

log = logging.getLogger("scraper.telegram")

BACKFILL_PER_CHAT = 80
CATCHUP_EVERY_SEC = 900  # 15 min — safety net if NewMessage is quiet
CATCHUP_PER_CHAT = 25


def _peer_id_variants(entity_or_id: Any) -> set[int]:
    """Telethon mixes bare channel ids and -100… peer ids — accept both."""
    out: set[int] = set()
    try:
        out.add(int(utils.get_peer_id(entity_or_id)))
    except Exception:
        pass
    try:
        raw = int(getattr(entity_or_id, "id", entity_or_id) or 0)
    except (TypeError, ValueError):
        raw = 0
    if raw:
        out.add(raw)
        out.add(-raw)
        # Channel / megagroup marked peer
        if raw > 0:
            out.add(int(f"-100{raw}"))
        s = str(abs(raw))
        if s.startswith("100") and len(s) > 3:
            try:
                out.add(int(s[3:]))
            except ValueError:
                pass
    return {x for x in out if x}


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
                err = str(exc).lower()
                if "need_qr_login" in err or "session_revoked" in err or "two different ip" in err:
                    # Dead session — do not hammer Telegram
                    backoff = max(backoff, 600.0)
            await self._safe_disconnect()
            if self._stopped:
                break
            await asyncio.sleep(backoff)
            backoff = min(backoff * 1.7, float(config.LISTENER_RETRY_SEC * 5))

    @staticmethod
    def _session_fingerprint() -> str:
        raw = (config.TG_SESSION or "").strip()
        if not raw:
            try:
                if config.TG_SESSION_FILE.exists():
                    raw = config.TG_SESSION_FILE.read_text(encoding="utf-8").strip()
            except Exception:
                raw = ""
        if not raw:
            raw = str(config.SESSION_PATH)
        return hashlib.sha256(raw.encode("utf-8", errors="ignore")).hexdigest()[:12]

    async def _backup_session_string(self) -> None:
        """Keep a copy of StringSession on the data volume (no secrets in logs)."""
        if not config.TG_SESSION:
            return
        try:
            dest = config.DB_PATH.parent / "tg_string.session.bak"
            dest.write_text(config.TG_SESSION.strip(), encoding="utf-8")
        except Exception as exc:
            log.debug("session backup skipped: %s", exc)

    @staticmethod
    def _purge_dead_session() -> None:
        for p in (
            Path(str(config.SESSION_PATH) + ".session"),
            Path(str(config.SESSION_PATH)),
            config.TG_SESSION_FILE,
        ):
            try:
                if p.exists() and p.is_file():
                    p.unlink()
                    log.warning("purged dead TG session file %s", p)
            except Exception:
                pass

    @staticmethod
    def _session_arg():
        """Cloud-safe session: TG_SESSION env → file string → classic .session path."""
        from telethon.sessions import StringSession

        if config.TG_SESSION:
            return StringSession(config.TG_SESSION)
        try:
            if config.TG_SESSION_FILE.exists():
                raw = config.TG_SESSION_FILE.read_text(encoding="utf-8").strip()
                if raw:
                    return StringSession(raw)
        except Exception:
            pass
        return str(config.SESSION_PATH)

    async def _connect_once(self) -> None:
        if not config.API_ID or not config.API_HASH:
            await self._save_health(ok=False, note="missing_api_creds")
            raise RuntimeError("missing_api_creds")
        proxy = config.telethon_proxy()
        kwargs: dict = {
            "session": self._session_arg(),
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
        try:
            await self.client.connect()
        except Exception as exc:
            msg = str(exc)
            if "two different IP" in msg or "AuthKeyDuplicated" in type(exc).__name__:
                self._purge_dead_session()
                await self._save_health(ok=False, note="need_qr_login")
                raise RuntimeError(
                    "session_revoked: open /tg-login and scan QR (do not run local hub with same session)"
                ) from exc
            raise
        if not await self.client.is_user_authorized():
            await self._save_health(ok=False, note="need_qr_login")
            raise RuntimeError("need_qr_login: open /tg-login and scan QR in Telegram")
        await self.client.start()
        me = await self.client.get_me()
        log.info("TG logged in as %s", me.username or me.first_name)
        await self._backup_session_string()
        self._resolved = 0
        self._failed = []
        self._ids.clear()
        for u in list(self._usernames):
            try:
                ent = await self.client.get_entity(u)
                self._ids |= _peer_id_variants(ent)
                self._resolved += 1
            except Exception as exc:
                self._failed.append(u)
                log.debug("resolve %s: %s", u, exc)
            await asyncio.sleep(0.2)
        self.client.add_event_handler(self.on_message, events.NewMessage(incoming=True))
        log.info(
            "TG watching %s usernames / %s ids (failed resolve %s)",
            len(self._usernames),
            len(self._ids),
            len(self._failed),
        )
        self._ok = True
        await self._save_health(ok=True, note="listening")
        asyncio.create_task(self._backfill())
        asyncio.create_task(self._catchup_loop())

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
                "session_fp": self._session_fingerprint(),
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
                        posted_at = None
                        if msg_ts is not None:
                            try:
                                posted_at = float(msg_ts.timestamp())
                            except Exception:
                                posted_at = None
                        raw = RawLoad(
                            source="telegram",
                            external_id=f"{username or ent.id}:{msg.id}",
                            title=(getattr(ent, "title", None) or username or "TG"),
                            body=text,
                            url=link,
                            posted_at=posted_at,
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

    async def _catchup_loop(self) -> None:
        """Re-scan recent messages if live NewMessage events go silent."""
        await asyncio.sleep(60)
        while not self._stopped:
            try:
                if self.client and self._ok:
                    n = await self._light_catchup()
                    if n:
                        log.info("TG catch-up added %s", n)
            except Exception as exc:
                log.warning("TG catch-up: %s", exc)
            await asyncio.sleep(CATCHUP_EVERY_SEC)

    async def _light_catchup(self) -> int:
        if not self.client:
            return 0
        added = 0
        self.db.begin_batch()
        try:
            for u in list(self._usernames):
                if self._stopped or not self.client:
                    break
                try:
                    ent = await self.client.get_entity(u)
                    async for msg in self.client.iter_messages(ent, limit=CATCHUP_PER_CHAT):
                        text = (msg.message or "").strip()
                        if len(text) < 20:
                            continue
                        msg_ts = getattr(msg, "date", None)
                        posted_at = None
                        if msg_ts is not None:
                            try:
                                posted_at = float(msg_ts.timestamp())
                                if time.time() - posted_at > config.MAX_LOAD_AGE_SEC:
                                    continue
                            except Exception:
                                posted_at = None
                        username = (getattr(ent, "username", None) or u or "").lower()
                        link = f"https://t.me/{username}/{msg.id}" if username else None
                        raw = RawLoad(
                            source="telegram",
                            external_id=f"{username or ent.id}:{msg.id}",
                            title=(getattr(ent, "title", None) or username or "TG"),
                            body=text,
                            url=link,
                            posted_at=posted_at,
                            raw={"chat": username, "msg_id": msg.id, "via": "catchup"},
                        )
                        status = await ingest_raw(self.db, raw, min_score=0, scoring="browse")
                        if status == "added":
                            added += 1
                except Exception as exc:
                    log.debug("TG catch-up %s: %s", u, exc)
                await asyncio.sleep(0.15)
        finally:
            await self.db.end_batch()
        if added:
            await self._save_health(ok=True, note=f"catchup_added:{added}")
        return added

    async def stop(self) -> None:
        self._stopped = True
        await self._safe_disconnect()
        if self._task:
            self._task.cancel()

    def _is_watched_chat(self, chat: Any, username: str) -> bool:
        if username and username in self._usernames:
            return True
        return bool(self._ids & _peer_id_variants(chat))

    async def on_message(self, event: events.NewMessage.Event) -> None:
        chat = await event.get_chat()
        if isinstance(chat, User):
            return
        username = (getattr(chat, "username", None) or "").lower()
        if not self._is_watched_chat(chat, username):
            return
        text = (event.raw_text or "").strip()
        if len(text) < 20:
            return
        record("live_seen", source="telegram")
        chat_id = int(getattr(chat, "id", 0) or 0)
        link = f"https://t.me/{username}/{event.id}" if username else None
        posted_at = None
        try:
            msg_date = getattr(event.message, "date", None) or getattr(event, "date", None)
            if msg_date is not None:
                posted_at = float(msg_date.timestamp())
        except Exception:
            posted_at = None
        raw = RawLoad(
            source="telegram",
            external_id=f"{username or chat_id}:{event.id}",
            title=(getattr(chat, "title", None) or username or "TG"),
            body=text,
            url=link,
            posted_at=posted_at,
            raw={"chat": username, "msg_id": event.id},
        )
        try:
            status = await ingest_raw(self.db, raw, min_score=0, scoring="browse")
            if status == "added":
                log.info("TG live +1 @%s", username or chat_id)
            await self._save_health(ok=True, note="listening")
        except Exception as exc:
            self._last_error = str(exc)
            log.warning("tg ingest: %s", exc)
            await self._save_health(ok=True, note="ingest_error")
