from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")

DB_PATH = Path(os.getenv("DB_PATH", str(ROOT / "data" / "hub.db")))
HOST = os.getenv("HOST", "127.0.0.1")
PORT = int(os.getenv("PORT", "8088"))
# Allow browser UI on another origin (e.g. Vercel static → Railway API)
CORS_ORIGINS = [
    o.strip()
    for o in os.getenv("CORS_ORIGINS", "").split(",")
    if o.strip()
]

# Telethon (optional TG ingest)
API_ID = int(os.getenv("API_ID", "0") or 0)
API_HASH = os.getenv("API_HASH", "").strip()
PHONE = os.getenv("PHONE", "").strip() or None
SESSION_NAME = os.getenv("SESSION_NAME", "freight_hub").strip()
# Absolute SESSION_NAME (e.g. /data/freight_hub) keeps Telethon session on the volume.
_session = Path(SESSION_NAME)
SESSION_PATH = _session if _session.is_absolute() else (ROOT / SESSION_NAME)
ENABLE_TG = os.getenv("ENABLE_TG", "1").strip() not in {"0", "false", "no"}

SCRAPE_INTERVAL_SEC = int(os.getenv("SCRAPE_INTERVAL_SEC", "300"))
SCRAPE_TICK_SEC = int(os.getenv("SCRAPE_TICK_SEC", "30"))
SCRAPE_CONCURRENCY = int(os.getenv("SCRAPE_CONCURRENCY", "4"))
MIN_SCORE = int(os.getenv("MIN_SCORE", "40"))
CROSS_DEDUP_HOURS = float(os.getenv("CROSS_DEDUP_HOURS", "6"))
WATCHDOG_SEC = int(os.getenv("WATCHDOG_SEC", "120"))
LISTENER_RETRY_SEC = int(os.getenv("LISTENER_RETRY_SEC", "60"))
# Feed / DB retention: drop loads older than this many days
MAX_LOAD_AGE_DAYS = float(os.getenv("MAX_LOAD_AGE_DAYS", "7"))
MAX_LOAD_AGE_SEC = MAX_LOAD_AGE_DAYS * 86400
USER_AGENT = os.getenv(
    "USER_AGENT",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
)

# Reuse TG chat list from freight_core defaults
MAX_TG_CHATS = int(os.getenv("MAX_TG_CHATS", "50"))
# When bot also runs: bot must set USE_HUB_INGEST=1 and not open the same .session
OWN_TELETHON = os.getenv("OWN_TELETHON", "1").strip() not in {"0", "false", "no"}
ENABLE_TG = ENABLE_TG and OWN_TELETHON
ATI_API_TOKEN = os.getenv("ATI_API_TOKEN", "").strip()
MONOPOLY_API_TOKEN = os.getenv("MONOPOLY_API_TOKEN", "").strip()

# Telegram MTProto proxy (t.me/proxy?server=&port=&secret=)
# Example secret starts with dd… for fake-TLS MTProxy.
TG_PROXY_SERVER = os.getenv("TG_PROXY_SERVER", "").strip()
TG_PROXY_PORT = int(os.getenv("TG_PROXY_PORT", "0") or 0)
TG_PROXY_SECRET = os.getenv("TG_PROXY_SECRET", "").strip()


def telethon_proxy() -> tuple | None:
    """Proxy args for Telethon MTProto (host, port, secret)."""
    if TG_PROXY_SERVER and TG_PROXY_PORT and TG_PROXY_SECRET:
        return (TG_PROXY_SERVER, TG_PROXY_PORT, TG_PROXY_SECRET)
    return None


# MAX messenger ingest (PyMax user session; unofficial API)
ENABLE_MAX = os.getenv("ENABLE_MAX", "1").strip() not in {"0", "false", "no"}
MAX_SESSION_NAME = os.getenv("MAX_SESSION_NAME", "freight_hub_max.db").strip()
MAX_CACHE_DIR = Path(os.getenv("MAX_CACHE_DIR", str(ROOT / "data" / "max_cache")))
