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
# Prefer StringSession for cloud (avoids dual-IP AuthKeyDuplicatedError with local .session).
TG_SESSION = os.getenv("TG_SESSION", "").strip()
TG_SESSION_FILE = Path(os.getenv("TG_SESSION_FILE", str(DB_PATH.parent / "tg_string.session")))
ENABLE_TG = os.getenv("ENABLE_TG", "1").strip() not in {"0", "false", "no"}

SCRAPE_INTERVAL_SEC = int(os.getenv("SCRAPE_INTERVAL_SEC", "300"))
SCRAPE_TICK_SEC = int(os.getenv("SCRAPE_TICK_SEC", "30"))
SCRAPE_CONCURRENCY = int(os.getenv("SCRAPE_CONCURRENCY", "4"))
MIN_SCORE = int(os.getenv("MIN_SCORE", "40"))
# Keep only declared tonnage in this band (tons). Unknown tonnage still allowed from messengers.
TONNAGE_MIN = float(os.getenv("TONNAGE_MIN", "5") or 5)
TONNAGE_MAX = float(os.getenv("TONNAGE_MAX", "12") or 12)
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
MAX_TG_CHATS = int(os.getenv("MAX_TG_CHATS", "70"))
# When bot also runs: bot must set USE_HUB_INGEST=1 and not open the same .session
OWN_TELETHON = os.getenv("OWN_TELETHON", "1").strip() not in {"0", "false", "no"}
ENABLE_TG = ENABLE_TG and OWN_TELETHON
ATI_API_TOKEN = os.getenv("ATI_API_TOKEN", "").strip()
MONOPOLY_API_TOKEN = os.getenv("MONOPOLY_API_TOKEN", "").strip()

# Vision / OCR for freight-board screenshot → rate analysis
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()
GEMINI_VISION_MODEL = os.getenv("GEMINI_VISION_MODEL", "gemini-flash-latest").strip()
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "").strip()
OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1").strip()
OPENAI_VISION_MODEL = os.getenv("OPENAI_VISION_MODEL", "gpt-4o-mini").strip()

# One-truck unit economics (defaults for the Moscow corridor machine)
TRUCK_LOAD_UNLOAD_HOURS = float(os.getenv("TRUCK_LOAD_UNLOAD_HOURS", "2.5") or 2.5)
TRUCK_DRIVER_DAY_RUB = float(os.getenv("TRUCK_DRIVER_DAY_RUB", "10000") or 10000)
TRUCK_FUEL_L_PER_100KM = float(os.getenv("TRUCK_FUEL_L_PER_100KM", "30") or 30)
TRUCK_DIESEL_RUB_PER_L = float(os.getenv("TRUCK_DIESEL_RUB_PER_L", "80") or 80)
TRUCK_AMORTIZATION_PCT = float(os.getenv("TRUCK_AMORTIZATION_PCT", "0.05") or 0.05)
TRUCK_TAX_PCT = float(os.getenv("TRUCK_TAX_PCT", "0.35") or 0.35)
TRUCK_TARGET_NET_MIN = float(os.getenv("TRUCK_TARGET_NET_MIN", "10000") or 10000)
TRUCK_TARGET_NET_MAX = float(os.getenv("TRUCK_TARGET_NET_MAX", "15000") or 15000)
TRUCK_AVG_SPEED_KMH = float(os.getenv("TRUCK_AVG_SPEED_KMH", "55") or 55)
BACKHAUL_RADIUS_KM = float(os.getenv("BACKHAUL_RADIUS_KM", "100") or 100)

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
# Extra MAX channel URLs (comma-separated), including max.ru/join/... invites
MAX_EXTRA_CHANNELS = [
    u.strip() for u in os.getenv("MAX_EXTRA_CHANNELS", "").split(",") if u.strip()
]

# Protect write endpoints (mute/profile/scrape/maintenance/tg-login APIs)
HUB_WRITE_TOKEN = os.getenv("HUB_WRITE_TOKEN", "").strip()
# If 1, inject token into HTML meta for same-origin UI (still visible in page source)
HUB_INJECT_UI_TOKEN = os.getenv("HUB_INJECT_UI_TOKEN", "1").strip() not in {"0", "false", "no"}

# Optional Telegram bot alerts for hot loads (score>=80)
ALERT_BOT_TOKEN = os.getenv("ALERT_BOT_TOKEN", "").strip()
ALERT_CHAT_ID = os.getenv("ALERT_CHAT_ID", "").strip()
ALERT_MIN_SCORE = int(os.getenv("ALERT_MIN_SCORE", "80") or 80)
ZERO_ADD_STREAK_WARN = int(os.getenv("ZERO_ADD_STREAK_WARN", "3") or 3)
