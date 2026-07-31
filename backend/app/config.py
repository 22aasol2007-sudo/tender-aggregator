from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "Tender Aggregator"
    database_url: str = "postgresql+psycopg://tender:tender@127.0.0.1:5432/tenders"
    sqlite_fallback_url: str = (
        f"sqlite:///{Path(__file__).resolve().parents[1] / 'data' / 'tenders.db'}"
    )
    db_pool_size: int = 10
    db_max_overflow: int = 20
    cors_origins: list[str] = ["http://localhost:5173", "http://127.0.0.1:5173"]
    scrape_interval_minutes: int = 5
    scrape_concurrency: int = 5
    http_timeout: float = 12.0
    http_verify_ssl: bool = True
    http_retries: int = 2
    http_cache_ttl_seconds: float = 180.0
    http_max_connections: int = 40
    http_max_keepalive: int = 20
    api_cache_ttl_seconds: float = 45.0
    approximate_count: bool = True
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
    # Enrich only brand-new tenders (not every scrape touch)
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


settings = Settings()
