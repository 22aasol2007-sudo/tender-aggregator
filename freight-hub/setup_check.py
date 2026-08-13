"""Phase 0 readiness check — no secrets printed."""

from __future__ import annotations

from pathlib import Path

from app import config


def main() -> None:
    session = Path(str(config.SESSION_PATH) + ".session")
    print("Freight Hub setup check")
    print(f"  API_ID set: {bool(config.API_ID)}")
    print(f"  API_HASH set: {bool(config.API_HASH)}")
    print(f"  ENABLE_TG: {config.ENABLE_TG}")
    print(f"  Session file: {session.exists()} ({session.name})")
    print(f"  DB: {config.DB_PATH}")
    if not config.API_ID or not config.API_HASH:
        print("")
        print("Next: Get API_ID/API_HASH at https://my.telegram.org")
        print("Put them in .env, then: python login_tg.py")
        print("Use VPN (e.g. Happ) if t.me times out")
        return
    if not session.exists():
        print("")
        print("Next: python login_tg.py")
        return
    print("")
    print("OK: credentials + session present. Start: python -m app.main")
    print("Bot: set USE_HUB_INGEST=1 so only hub opens Telethon.")


if __name__ == "__main__":
    main()
