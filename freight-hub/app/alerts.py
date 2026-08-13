"""Optional Telegram alerts for hot loads and source drought."""

from __future__ import annotations

import logging
from typing import Any

import httpx

from app import config

log = logging.getLogger("alerts")


async def send_alert(text: str) -> bool:
    token = config.ALERT_BOT_TOKEN
    chat = config.ALERT_CHAT_ID
    if not token or not chat:
        return False
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            r = await client.post(
                f"https://api.telegram.org/bot{token}/sendMessage",
                json={"chat_id": chat, "text": text[:3500], "disable_web_page_preview": True},
            )
            if r.status_code >= 400:
                log.warning("alert failed %s %s", r.status_code, r.text[:200])
                return False
            return True
    except Exception as exc:
        log.warning("alert error: %s", exc)
        return False


async def maybe_alert_hot(item: dict[str, Any]) -> None:
    score = int(item.get("score") or 0)
    if score < config.ALERT_MIN_SCORE:
        return
    frm = item.get("from_city") or "?"
    to = item.get("to_city") or "?"
    ppk = item.get("price_per_km")
    ppk_s = f", {ppk} ₽/км" if ppk is not None else ""
    price = item.get("price") or ""
    url = item.get("url") or ""
    text = (
        f"🔥 Горячая ≥{config.ALERT_MIN_SCORE}: {frm} → {to}\n"
        f"скор {score}{ppk_s}"
        + (f"\n{price}" if price else "")
        + (f"\n{url}" if url else "")
    )
    await send_alert(text)


async def maybe_alert_zero_streak(source: str, streak: int) -> None:
    if streak < config.ZERO_ADD_STREAK_WARN:
        return
    await send_alert(
        f"⚠️ Источник «{source}»: 0 добавлений {streak} циклов подряд"
    )
