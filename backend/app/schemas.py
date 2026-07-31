from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class TenderOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    external_id: str
    source: str
    law: str | None = None
    title: str
    customer: str | None = None
    customer_inn: str | None = None
    region: str | None = None
    price: float | None = None
    currency: str = "RUB"
    status: str | None = None
    status_norm: str = "unknown"
    method: str | None = None
    okpd2: str | None = None
    url: str
    description: str | None = None
    documents: list[dict[str, Any]] | None = None
    lots: list[dict[str, Any]] | None = None
    fingerprint: str | None = None
    is_duplicate: bool = False
    duplicate_of_id: int | None = None
    published_at: datetime | None = None
    deadline_at: datetime | None = None
    enriched_at: datetime | None = None
    scraped_at: datetime | None = None
    changed_at: datetime | None = None
    customer_id: int | None = None
    customer_kpp: str | None = None
    relevance: int | None = None
    watch_status: str | None = None


class TenderListResponse(BaseModel):
    items: list[TenderOut]
    total: int
    page: int
    page_size: int


class TenderChangeOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    field: str
    old_value: str | None = None
    new_value: str | None = None
    changed_at: datetime


class StatsOut(BaseModel):
    total: int
    active: int
    by_source: dict[str, int]
    by_law: dict[str, int]
    last_scrape: datetime | None = None
    database: str


class DashboardOut(BaseModel):
    total: int
    active: int
    avg_price: float | None = None
    new_day: int
    new_week: int
    changed_day: int
    top_regions: list[dict[str, Any]]
    by_source: dict[str, int]
    series: list[dict[str, Any]]
    last_scrape: datetime | None = None


class ScrapeRunOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    source: str
    status: str
    fetched: int
    upserted: int
    skipped: int = 0
    error: str | None = None
    started_at: datetime
    finished_at: datetime | None = None


class ScrapeRequest(BaseModel):
    sources: list[str] | None = None


class HealthOut(BaseModel):
    status: str
    app: str
    tenders: int
    database: str


class FilterPresetOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    description: str | None = None
    filters: dict[str, Any]
    is_builtin: bool = False
    is_shared: bool = False
    user_id: int | None = None


class FilterPresetIn(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    description: str | None = None
    filters: dict[str, Any] = Field(default_factory=dict)
    is_shared: bool = False


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: "UserOut"


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    email: str
    name: str
    is_admin: bool
    telegram_chat_id: str | None = None


class RegisterIn(BaseModel):
    email: str
    password: str = Field(min_length=6)
    name: str = "Пользователь"


class LoginIn(BaseModel):
    email: str
    password: str


class ProfileOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    company_name: str | None = None
    okpd_prefixes: list[Any] = Field(default_factory=list)
    regions: list[Any] = Field(default_factory=list)
    keywords: list[Any] = Field(default_factory=list)
    min_price: float | None = None
    max_price: float | None = None


class ProfileIn(BaseModel):
    company_name: str | None = None
    okpd_prefixes: list[str] = Field(default_factory=list)
    regions: list[str] = Field(default_factory=list)
    keywords: list[str] = Field(default_factory=list)
    min_price: float | None = None
    max_price: float | None = None


class TelegramIn(BaseModel):
    telegram_chat_id: str | None = None


class WatchIn(BaseModel):
    status: str = "favorite"
    notes: str | None = None
    tags: list[str] = Field(default_factory=list)


class WatchOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    tender_id: int
    status: str
    notes: str | None = None
    tags: list[Any] = Field(default_factory=list)
    tender: TenderOut | None = None


class SavedSearchIn(BaseModel):
    name: str
    filters: dict[str, Any] = Field(default_factory=dict)
    notify_telegram: bool = True


class SavedSearchOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    filters: dict[str, Any]
    new_count: int
    notify_telegram: bool
    updated_at: datetime | None = None


class CustomerOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    inn: str | None = None
    kpp: str | None = None
    name: str
    holding_name: str | None = None
    region: str | None = None
    tender_count: int = 0
    total_price: float = 0
    in_rnp: bool = False
    has_bank_guarantee: bool | None = None
    compliance_checked_at: datetime | None = None
    compliance_notes: str | None = None
    last_seen_at: datetime | None = None


class CustomerDetailOut(CustomerOut):
    history: list[TenderOut] = Field(default_factory=list)


class JobOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    job_type: str
    payload: dict[str, Any] = Field(default_factory=dict)
    priority: int = 100
    status: str
    result: dict[str, Any] | None = None
    error: str | None = None
    created_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None


class ScrapeEnqueueOut(BaseModel):
    mode: str
    job: JobOut | None = None
    runs: list[ScrapeRunOut] | None = None
