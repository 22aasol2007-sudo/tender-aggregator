"""One-time MAX login for Freight Hub (PyMax WebClient + QR + optional 2FA).

Scan QR in MAX app. If account has 2FA password, set MAX_2FA_PASSWORD in .env
for this login only (do not paste it in chat). Session is saved under data/max_cache/.
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path

import qrcode

from app import config
from app.defaults_max import DEFAULT_MAX_CHANNELS

ROOT = Path(__file__).resolve().parent
CACHE = Path(config.MAX_CACHE_DIR)
QR_PATH = ROOT / "max_login_qr.png"


class FileAndConsoleQr:
    async def show_qr(self, qr_url: str) -> None:
        print()
        print("Откройте MAX на телефоне и отсканируйте QR (вход / устройства).")
        print(f"PNG: {QR_PATH}")
        print(f"URL: {qr_url}")
        print()
        qr = qrcode.QRCode()
        qr.add_data(qr_url)
        qr.print_ascii(invert=True)
        qrcode.make(qr_url).save(QR_PATH)


class EnvOrConsolePassword:
    """Prefer MAX_2FA_PASSWORD from env; otherwise ask in console."""

    async def get_password(self, hint: str | None = None) -> str:
        env_pw = os.getenv("MAX_2FA_PASSWORD", "").strip()
        if env_pw:
            print(f"2FA: использую MAX_2FA_PASSWORD из .env (hint={hint!r})")
            return env_pw
        print()
        print("Нужен пароль 2FA MAX (не код из SMS).")
        if hint:
            print(f"Подсказка: {hint}")
        print("Либо добавьте MAX_2FA_PASSWORD=... в .env и перезапустите login_max.py")
        try:
            import getpass

            return getpass.getpass("Пароль 2FA: ")
        except Exception:
            return input("Пароль 2FA: ").strip()


async def main() -> None:
    from pymax import QrAuthFlow, WebClient

    CACHE.mkdir(parents=True, exist_ok=True)
    done = asyncio.Event()
    client = WebClient(
        session_name=config.MAX_SESSION_NAME,
        work_dir=str(CACHE),
        auth_flow=QrAuthFlow(
            qr_provider=FileAndConsoleQr(),
            password_provider=EnvOrConsolePassword(),
        ),
    )

    @client.on_start()
    async def on_start(c: WebClient) -> None:
        me = c.me
        contact = getattr(me, "contact", None) if me else None
        uid = getattr(contact, "id", None)
        print(f"OK: MAX login id={uid}")
        print(f"Session: {CACHE / config.MAX_SESSION_NAME}")
        for ch in DEFAULT_MAX_CHANNELS:
            link = ch["url"]
            try:
                try:
                    chat = await c.join_channel(link)
                except Exception:
                    chat = await c.resolve_group_by_link(link)
                if chat:
                    print(f"  + {getattr(chat, 'title', ch['title'])} id={chat.id}")
                else:
                    print(f"  ! empty: {link}")
            except Exception as exc:
                print(f"  ! {link}: {exc}")
            await asyncio.sleep(0.3)
        done.set()
        try:
            await c.stop()
        except Exception:
            pass

    print("QR-логин MAX…")
    if not os.getenv("MAX_2FA_PASSWORD", "").strip():
        print("Если спросит 2FA — нужен MAX_2FA_PASSWORD в .env (не присылайте пароль в чат).")
    task = asyncio.create_task(client.start())
    try:
        await asyncio.wait_for(done.wait(), timeout=300)
        print("Готово. Можно запускать hub — MAX ingest подхватит сессию.")
    except asyncio.TimeoutError:
        print("Таймаут 5 мин — QR/2FA не подтвердили.")
    finally:
        if not task.done():
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):
                pass


if __name__ == "__main__":
    asyncio.run(main())
