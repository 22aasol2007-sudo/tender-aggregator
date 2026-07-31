from __future__ import annotations

import httpx

from app.config import settings


async def send_telegram_message(chat_id: str, text: str) -> bool:
    if not settings.telegram_enabled or not settings.telegram_bot_token or not chat_id:
        return False
    url = f"https://api.telegram.org/bot{settings.telegram_bot_token}/sendMessage"
    async with httpx.AsyncClient(timeout=20.0) as client:
        resp = await client.post(
            url,
            json={"chat_id": chat_id, "text": text[:3900], "disable_web_page_preview": True},
        )
        return resp.status_code == 200


async def notify_new_tenders(chat_id: str, search_name: str, tenders: list) -> None:
    if not tenders:
        return
    lines = [f"🔔 Новые по «{search_name}»: {len(tenders)}"]
    for t in tenders[:8]:
        price = f"{t.price:,.0f} ₽".replace(",", " ") if t.price else "—"
        lines.append(f"• {t.title[:120]}\n  {price} · {t.source}\n  {t.url}")
    await send_telegram_message(chat_id, "\n".join(lines))
