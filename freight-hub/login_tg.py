"""One-time Telegram login for Freight Hub (Telethon session)."""

from __future__ import annotations

import asyncio
import getpass

from telethon import TelegramClient

from app import config


def _ask_phone() -> str:
    while True:
        raw = input("Номер телефона (как в Telegram, с +): ").strip()
        if raw.startswith("+") and len(raw) >= 11:
            return raw
        print("Пример: +79001234567")


def _ask_code() -> str:
    return input("Код из Telegram/SMS: ").strip()


def _ask_password() -> str:
    print()
    print("Нужен пароль двухэтапной проверки Telegram (Settings → Privacy → 2FA),")
    print("НЕ код из SMS и НЕ токен бота. При вводе символы не видны — это нормально.")
    return getpass.getpass("Пароль 2FA: ")


async def main() -> None:
    if not config.API_ID or not config.API_HASH:
        print("Сначала заполни API_ID и API_HASH в .env (https://my.telegram.org)")
        return
    phone = config.PHONE or _ask_phone
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
        print(f"MTProxy: {config.TG_PROXY_SERVER}:{config.TG_PROXY_PORT}")
    client = TelegramClient(**kwargs)
    await client.start(phone=phone, code_callback=_ask_code, password=_ask_password)
    me = await client.get_me()
    print(f"OK: вошли как {me.username or me.first_name}. Сессия: {config.SESSION_PATH}.session")
    await client.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
