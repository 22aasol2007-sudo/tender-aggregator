"""MAX messenger ingest via PyMax WebClient (user session)."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any

from app import config
from app.defaults_max import DEFAULT_MAX_CHANNELS
from app.ingest import ingest_raw
from app.models import RawLoad

if TYPE_CHECKING:
    from app.db import HubDB

log = logging.getLogger("scraper.max")

BACKFILL_PER_CHAT = 60


class MaxIngest:
    name = "max"

    def __init__(self, db: "HubDB") -> None:
        self.db = db
        self.client: Any = None
        self._chat_ids: set[int] = set()
        self._id_to_meta: dict[int, dict[str, str]] = {}
        self._resolved = 0
        self._failed: list[str] = []
        self._backfill_added = 0
        self._last_error: str | None = None
        self._channels = list(DEFAULT_MAX_CHANNELS)
        self._stopped = False
        self._task: asyncio.Task | None = None
        self._ok = False
        self._run_task: asyncio.Task | None = None

    @property
    def ok(self) -> bool:
        return self._ok

    async def start(self) -> None:
        self._stopped = False
        cache = Path(config.MAX_CACHE_DIR)
        cache.mkdir(parents=True, exist_ok=True)
        session = cache / config.MAX_SESSION_NAME
        if not session.exists():
            await self._save_health(
                ok=False,
                note="no_session",
                hint="Run: python login_max.py and scan QR in MAX app",
            )
            log.warning("MAX disabled: no session at %s", session)
            return
        self._task = asyncio.create_task(self._supervise())

    async def _supervise(self) -> None:
        backoff = 5.0
        while not self._stopped:
            try:
                await self._connect_once()
                backoff = 5.0
                while not self._stopped and self._ok:
                    await asyncio.sleep(20)
                    await self._save_health(ok=True, note="listening")
                if self._stopped:
                    break
            except Exception as exc:
                self._ok = False
                self._last_error = str(exc)
                log.warning("MAX supervise: %r — retry in %.0fs", exc, backoff)
                await self._save_health(ok=False, note=f"reconnect: {exc!r}")
            await self._safe_stop_client()
            if self._stopped:
                break
            await asyncio.sleep(backoff)
            backoff = min(backoff * 1.7, float(config.LISTENER_RETRY_SEC * 5))

    async def _connect_once(self) -> None:
        from pymax import Message, WebClient

        cache = Path(config.MAX_CACHE_DIR)
        self.client = WebClient(
            session_name=config.MAX_SESSION_NAME,
            work_dir=str(cache),
        )
        ready = asyncio.Event()

        @self.client.on_start()
        async def _on_start(c: Any) -> None:
            await self._resolve_channels(c)
            self._ok = True
            await self._save_health(ok=True, note="listening")
            ready.set()
            asyncio.create_task(self._backfill(c))

        @self.client.on_message()
        async def _on_message(message: Message, c: Any) -> None:
            await self._handle_message(message)

        log.info("MAX starting (session %s)…", config.MAX_SESSION_NAME)
        self._run_task = asyncio.create_task(self.client.start())
        try:
            await asyncio.wait_for(ready.wait(), timeout=25)
        except asyncio.TimeoutError as exc:
            self._last_error = "connect timeout (web.max.ru)"
            raise TimeoutError(self._last_error) from exc

    async def _safe_stop_client(self) -> None:
        self._ok = False
        if self.client:
            for name in ("stop", "disconnect", "close"):
                fn = getattr(self.client, name, None)
                if callable(fn):
                    try:
                        res = fn()
                        if asyncio.iscoroutine(res):
                            await res
                        break
                    except Exception:
                        pass
            self.client = None
        if self._run_task and not self._run_task.done():
            self._run_task.cancel()
            try:
                await self._run_task
            except (asyncio.CancelledError, Exception):
                pass
        self._run_task = None

    async def _resolve_channels(self, c: Any) -> None:
        self._resolved = 0
        self._failed = []
        self._chat_ids.clear()
        self._id_to_meta.clear()
        for ch in self._channels:
            link = ch["url"]
            slug = ch["slug"]
            try:
                try:
                    chat = await c.join_channel(link)
                except Exception:
                    chat = await c.resolve_group_by_link(link)
                if not chat or not getattr(chat, "id", None):
                    raise RuntimeError("empty chat")
                cid = int(chat.id)
                self._chat_ids.add(cid)
                self._id_to_meta[cid] = {
                    "slug": slug,
                    "title": getattr(chat, "title", None) or ch.get("title") or slug,
                    "url": link,
                }
                self._resolved += 1
                log.info("MAX resolved %s -> %s", slug, cid)
            except Exception as exc:
                self._failed.append(slug)
                log.warning("MAX resolve %s: %s", slug, exc)
            await asyncio.sleep(0.3)
        log.info(
            "MAX watching %s chats (failed %s)",
            len(self._chat_ids),
            len(self._failed),
        )

    async def _save_health(self, *, ok: bool, note: str, hint: str | None = None) -> None:
        data: dict[str, Any] = {
            "ok": ok,
            "note": note,
            "resolved": self._resolved,
            "watched": len(self._chat_ids),
            "failed": self._failed[:20],
            "failed_count": len(self._failed),
            "backfill_added": self._backfill_added,
            "last_error": self._last_error,
            "updated_at": time.time(),
        }
        if hint:
            data["hint"] = hint
        await self.db.set_setting("max_health", json.dumps(data, ensure_ascii=False))

    async def _backfill(self, c: Any) -> None:
        added = 0
        self.db.begin_batch()
        try:
            for cid, meta in list(self._id_to_meta.items()):
                try:
                    msgs = await c.fetch_history(cid, backward=BACKFILL_PER_CHAT)
                    for msg in msgs or []:
                        text = (getattr(msg, "text", None) or "").strip()
                        if len(text) < 20:
                            continue
                        msg_ts = getattr(msg, "time", None) or getattr(msg, "timestamp", None)
                        if msg_ts is not None:
                            try:
                                ts = float(msg_ts.timestamp()) if hasattr(msg_ts, "timestamp") else float(msg_ts)
                                # MAX sometimes uses ms
                                if ts > 1e12:
                                    ts /= 1000.0
                                if time.time() - ts > config.MAX_LOAD_AGE_SEC:
                                    continue
                            except Exception:
                                pass
                        mid = getattr(msg, "id", None) or getattr(msg, "cid", None) or id(msg)
                        raw = RawLoad(
                            source="max",
                            external_id=f"{meta['slug']}:{mid}",
                            title=meta["title"],
                            body=text,
                            url=meta["url"],
                            raw={"chat": meta["slug"], "msg_id": mid, "via": "backfill"},
                        )
                        status = await ingest_raw(self.db, raw, min_score=0, scoring="browse")
                        if status == "added":
                            added += 1
                    await asyncio.sleep(0.4)
                except Exception as exc:
                    self._last_error = f"backfill {meta['slug']}: {exc}"
                    log.debug("%s", self._last_error)
        finally:
            await self.db.end_batch()
        self._backfill_added = added
        log.info("MAX backfill done, added=%s", added)
        await self._save_health(ok=True, note="backfill_done")

    async def _handle_message(self, message: Any) -> None:
        chat_id = getattr(message, "chat_id", None)
        if chat_id is None:
            return
        cid = int(chat_id)
        if cid not in self._chat_ids:
            return
        text = (getattr(message, "text", None) or "").strip()
        if len(text) < 20:
            return
        meta = self._id_to_meta.get(cid) or {
            "slug": str(cid),
            "title": "MAX",
            "url": None,
        }
        mid = getattr(message, "id", None) or getattr(message, "cid", None)
        raw = RawLoad(
            source="max",
            external_id=f"{meta['slug']}:{mid}",
            title=meta["title"],
            body=text,
            url=meta.get("url"),
            raw={"chat": meta["slug"], "msg_id": mid},
        )
        try:
            await ingest_raw(self.db, raw, min_score=0, scoring="browse")
            await self._save_health(ok=True, note="listening")
        except Exception as exc:
            self._last_error = str(exc)
            log.warning("max ingest: %s", exc)
            await self._save_health(ok=True, note="ingest_error")

    async def stop(self) -> None:
        self._stopped = True
        await self._safe_stop_client()
        if self._task:
            self._task.cancel()
