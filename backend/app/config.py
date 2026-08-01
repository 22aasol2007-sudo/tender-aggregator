from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated

from pydantic import field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


def _normalize_database_url(url: str) -> str:
    if url.startswith("postgres://"):
        return "postgresql+psycopg://" + url[len("postgres://") :]
    if url.startswith("postgresql://") and "+psycopg" not in url:
        return "postgresql+psycopg://" + url[len("postgresql://") :]
    return url


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "Tender Aggregator"
    database_url: str = "postgresql+psycopg://tender:tender@127.0.0.1:5432/tenders"
    sqlite_fallback_url: str = (
        f"sqlite:///{Path(__file__).resolve().parents[1] / 'data' / 'tenders.db'}"
    )
    allow_sqlite_fallback: bool = False
    db_connect_timeout: int = 15
    db_pool_size: int = 5
    db_max_overflow: int = 10
    db_pool_recycle: int = 280
    db_statement_retries: int = 2
    cors_origins: Annotated[list[str], NoDecode] = [
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "https://tender-aggregator-lac.vercel.app",
        "https://tender-aggregator-22aasol2007-sudos-projects.vercel.app",
        "https://tender-aggregator-22aasol2007-sudo-22aasol2007-sudos-projects.vercel.app",
    ]
    scrape_interval_minutes: int = 3
    scrape_concurrency: int = 3
    scrape_source_timeout_seconds: float = 90.0
    scrape_job_timeout_seconds: float = 600.0
    stale_running_job_minutes: int = 20
    # Legacy single timeout (used as default read if http_read_timeout unset)
    http_timeout: float = 35.0
    http_connect_timeout: float = 12.0
    http_read_timeout: float = 35.0
    # Extra read budget for .gov.ru / commercial ETPs from abroad (US/EU→RU)
    http_ru_read_timeout: float = 35.0
    http_verify_ssl: bool = True
    # Total GET attempts (not "extra" retries). Keep ≤3 so dead hosts don't starve API.
    http_retries: int = 2
    http_retry_statuses: Annotated[list[int], NoDecode] = [429, 502, 503, 504]
    http_cache_ttl_seconds: float = 180.0
    http_max_connections: int = 40
    http_max_keepalive: int = 20
    # Optional egress proxy for RU hosts (http://user:pass@host:port or socks5://…)
    scrape_proxy_url: str | None = None
    http_proxy: str | None = None
    https_proxy: str | None = None
    all_proxy: str | None = None
    api_cache_ttl_seconds: float = 45.0
    approximate_count: bool = False
    fail_fast_failures: int = 3
    user_agent: str = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/131.0.0.0 Safari/537.36"
    )
    seed_if_empty: bool = True
    hide_outdated_default: bool = True
    jwt_secret: str = "tender-aggregator-dev-secret-change-me"
    jwt_expire_hours: int = 72
    default_admin_email: str = "admin@tender.local"
    default_admin_password: str = "admin123"
    telegram_bot_token: str | None = None
    telegram_enabled: bool = True
    enrich_on_scrape: bool = False
    enrich_new_only: bool = True
    enrich_limit_per_scrape: int = 8
    source_silence_minutes: int = 30
    monitor_telegram_chat_id: str | None = None
    scrape_via_worker: bool = True
    contour_api_url: str | None = None
    contour_api_token: str | None = None
    tenderplan_api_url: str | None = None
    tenderplan_api_token: str | None = None
    tenderland_api_url: str | None = None
    tenderland_api_token: str | None = None
    synapse_api_url: str | None = None
    synapse_api_token: str | None = None

    @field_validator("database_url", mode="before")
    @classmethod
    def normalize_db(cls, v: str) -> str:
        return _normalize_database_url(str(v))

    @field_validator("cors_origins", mode="before")
    @classmethod
    def parse_cors(cls, v):  # noqa: ANN001
        defaults = [
            "http://localhost:5173",
            "http://127.0.0.1:5173",
            "https://tender-aggregator-lac.vercel.app",
            "https://tender-aggregator-22aasol2007-sudos-projects.vercel.app",
            "https://tender-aggregator-22aasol2007-sudo-22aasol2007-sudos-projects.vercel.app",
        ]
        if v is None or v == "":
            return defaults
        if isinstance(v, list):
            return v
        text = str(v).strip()
        if text.startswith("["):
            try:
                parsed = json.loads(text)
                if isinstance(parsed, list):
                    return [str(x) for x in parsed]
            except json.JSONDecodeError:
                pass
        return [part.strip() for part in text.split(",") if part.strip()]

    @field_validator("http_retry_statuses", mode="before")
    @classmethod
    def parse_retry_statuses(cls, v):  # noqa: ANN001
        if v is None or v == "":
            return [429, 502, 503, 504]
        if isinstance(v, list):
            return [int(x) for x in v]
        text = str(v).strip()
        if text.startswith("["):
            try:
                parsed = json.loads(text)
                if isinstance(parsed, list):
                    return [int(x) for x in parsed]
            except json.JSONDecodeError:
                pass
        return [int(part.strip()) for part in text.split(",") if part.strip()]


settings = Settings()
