"""QR / StringSession login helpers for cloud-only Telegram (no dual-IP)."""

from __future__ import annotations

import asyncio
import base64
import io
import logging
from pathlib import Path
from typing import Any

from telethon import TelegramClient
from telethon.sessions import StringSession

from app import config

log = logging.getLogger("tg.login")

_lock = asyncio.Lock()
_state: dict[str, Any] = {
    "client": None,
    "qr": None,
    "url": None,
    "status": "idle",
    "error": None,
}


def _client_kwargs(session: StringSession) -> dict:
    kwargs: dict = {
        "session": session,
        "api_id": config.API_ID,
        "api_hash": config.API_HASH,
    }
    proxy = config.telethon_proxy()
    if proxy:
        from telethon.network import ConnectionTcpMTProxyRandomizedIntermediate

        kwargs["connection"] = ConnectionTcpMTProxyRandomizedIntermediate
        kwargs["proxy"] = proxy
    return kwargs


def _png_b64(url: str) -> str:
    import qrcode

    img = qrcode.make(url)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode("ascii")


def _save_string(client: TelegramClient) -> str:
    raw = client.session.save()
    config.TG_SESSION_FILE.parent.mkdir(parents=True, exist_ok=True)
    config.TG_SESSION_FILE.write_text(raw, encoding="utf-8")
    dead = Path(str(config.SESSION_PATH) + ".session")
    try:
        if dead.exists():
            dead.unlink()
    except Exception:
        pass
    return raw


async def start_qr() -> dict[str, Any]:
    if not config.API_ID or not config.API_HASH:
        return {"ok": False, "error": "missing_api_creds"}
    async with _lock:
        await _cancel_unlocked()
        client = TelegramClient(**_client_kwargs(StringSession()))
        await client.connect()
        if await client.is_user_authorized():
            _save_string(client)
            await client.disconnect()
            _state.update({"status": "already", "url": None, "error": None, "client": None, "qr": None})
            return {"ok": True, "status": "already", "hint": "session already authorized"}
        qr = await client.qr_login()
        _state.update(
            {
                "client": client,
                "qr": qr,
                "url": qr.url,
                "status": "waiting",
                "error": None,
            }
        )
        return {
            "ok": True,
            "status": "waiting",
            "url": qr.url,
            "qr_png_base64": _png_b64(qr.url),
            "hint": "Откройте Telegram → Сканировать QR",
        }


async def wait_qr(timeout: float = 120.0) -> dict[str, Any]:
    async with _lock:
        client = _state.get("client")
        qr = _state.get("qr")
        if not client or not qr:
            return {"ok": False, "status": _state.get("status") or "idle", "error": "no_active_qr"}
        try:
            await asyncio.wait_for(qr.wait(), timeout=timeout)
            _save_string(client)
            me = await client.get_me()
            await client.disconnect()
            _state.update(
                {
                    "client": None,
                    "qr": None,
                    "url": None,
                    "status": "done",
                    "error": None,
                }
            )
            return {
                "ok": True,
                "status": "done",
                "user": me.username or me.first_name,
                "hint": "Сессия сохранена. Telegram перезапустится автоматически.",
            }
        except Exception as exc:
            _state["error"] = str(exc)
            _state["status"] = "error"
            try:
                await client.disconnect()
            except Exception:
                pass
            _state["client"] = None
            _state["qr"] = None
            return {"ok": False, "status": "error", "error": str(exc)}


async def _cancel_unlocked() -> None:
    client = _state.get("client")
    if client:
        try:
            await client.disconnect()
        except Exception:
            pass
    _state.update({"client": None, "qr": None, "url": None, "status": "idle", "error": None})
