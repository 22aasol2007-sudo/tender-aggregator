"""QR / StringSession login helpers for cloud-only Telegram (no dual-IP)."""

from __future__ import annotations

import asyncio
import base64
import io
import logging
from pathlib import Path
from typing import Any

from telethon import TelegramClient
from telethon.errors import SessionPasswordNeededError
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


async def _finish_ok(client: TelegramClient) -> dict[str, Any]:
    _save_string(client)
    me = await client.get_me()
    try:
        await client.disconnect()
    except Exception:
        pass
    _state.update({"client": None, "qr": None, "url": None, "status": "done", "error": None})
    return {
        "ok": True,
        "status": "done",
        "user": me.username or me.first_name,
        "hint": "Сессия сохранена. Telegram перезапустится автоматически.",
    }


async def start_qr() -> dict[str, Any]:
    if not config.API_ID or not config.API_HASH:
        return {"ok": False, "error": "missing_api_creds"}
    async with _lock:
        await _cancel_unlocked()
        client = TelegramClient(**_client_kwargs(StringSession()))
        await client.connect()
        if await client.is_user_authorized():
            out = await _finish_ok(client)
            out["status"] = "already"
            out["hint"] = "session already authorized"
            return out
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
        _state["status"] = "waiting"
    try:
        await asyncio.wait_for(qr.wait(), timeout=timeout)
        async with _lock:
            return await _finish_ok(client)
    except SessionPasswordNeededError:
        async with _lock:
            _state["status"] = "need_2fa"
            _state["error"] = None
            _state["qr"] = None  # keep client connected
            return {
                "ok": False,
                "status": "need_2fa",
                "error": "need_2fa",
                "hint": "Введите пароль двухэтапной проверки Telegram (2FA), не SMS-код.",
            }
    except Exception as exc:
        msg = str(exc) or repr(exc)
        # Telethon sometimes wraps SessionPasswordNeededError
        if "password is required" in msg.lower() or "SessionPasswordNeeded" in type(exc).__name__:
            async with _lock:
                _state["status"] = "need_2fa"
                _state["error"] = None
                _state["qr"] = None
                return {
                    "ok": False,
                    "status": "need_2fa",
                    "error": "need_2fa",
                    "hint": "Введите пароль двухэтапной проверки Telegram (2FA), не SMS-код.",
                }
        async with _lock:
            _state["error"] = msg
            _state["status"] = "error"
            try:
                await client.disconnect()
            except Exception:
                pass
            _state["client"] = None
            _state["qr"] = None
            return {"ok": False, "status": "error", "error": msg}


async def submit_2fa(password: str) -> dict[str, Any]:
    password = (password or "").strip()
    if not password:
        return {"ok": False, "status": "need_2fa", "error": "empty_password"}
    async with _lock:
        client = _state.get("client")
        if not client:
            return {"ok": False, "status": "idle", "error": "no_active_login"}
        try:
            await client.sign_in(password=password)
            return await _finish_ok(client)
        except Exception as exc:
            _state["status"] = "need_2fa"
            _state["error"] = str(exc) or repr(exc)
            return {
                "ok": False,
                "status": "need_2fa",
                "error": str(exc) or repr(exc),
                "hint": "Неверный пароль 2FA. Попробуйте ещё раз.",
            }


async def _cancel_unlocked() -> None:
    client = _state.get("client")
    if client:
        try:
            await client.disconnect()
        except Exception:
            pass
    _state.update({"client": None, "qr": None, "url": None, "status": "idle", "error": None})
