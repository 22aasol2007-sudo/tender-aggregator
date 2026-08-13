"""Create a cloud-only Telegram StringSession via QR (local one-shot).

Saves freight-hub/data/tg_string.session — upload to Railway TG_SESSION / volume.
Do NOT start local hub with this session.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from telethon import TelegramClient  # noqa: E402
from telethon.sessions import StringSession  # noqa: E402

from app import config  # noqa: E402


async def main() -> None:
    if not config.API_ID or not config.API_HASH:
        print("Need API_ID/API_HASH in .env")
        return
    kwargs: dict = {
        "session": StringSession(),
        "api_id": config.API_ID,
        "api_hash": config.API_HASH,
    }
    proxy = config.telethon_proxy()
    if proxy:
        from telethon.network import ConnectionTcpMTProxyRandomizedIntermediate

        kwargs["connection"] = ConnectionTcpMTProxyRandomizedIntermediate
        kwargs["proxy"] = proxy
        print(f"MTProxy {config.TG_PROXY_SERVER}:{config.TG_PROXY_PORT}")
    client = TelegramClient(**kwargs)
    await client.connect()
    qr = await client.qr_login()
    out = ROOT / "data" / "tg_qr.png"
    out.parent.mkdir(parents=True, exist_ok=True)
    try:
        import qrcode

        qrcode.make(qr.url).save(out)
        print(f"QR saved: {out}")
    except Exception:
        pass
    print("Scan this QR in Telegram (Settings → Devices):")
    print(qr.url)
    await qr.wait()
    raw = client.session.save()
    dest = ROOT / "data" / "tg_string.session"
    dest.write_text(raw, encoding="utf-8")
    me = await client.get_me()
    print(f"OK @{me.username or me.first_name}")
    print(f"String session saved: {dest}")
    await client.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
