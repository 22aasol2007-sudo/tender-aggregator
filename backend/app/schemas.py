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
    freight_matched: int = 0
    total_tenders: int = 0


class NichePresetOut(BaseModel):
    name: str
    q: str
    exclude: str
    match_any: bool = True


class NicheOut(BaseModel):
    short_q: str
    full_q: str
    exclude: str
    okpd: list[str] = Field(default_factory=list)
    eis_search_passes: list[str] = Field(default_factory=list)
    search_engine: str | None = None
    presets: dict[str, NichePresetOut] = Field(default_factory=dict)


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
    db_ok: bool = True
    detail: str | None = None


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
    private_only: bool = False
    share_consent: bool = False
    niche_id: str | None = "cosmetics_moscow_gofra"


class ProfileIn(BaseModel):
    company_name: str | None = None
    okpd_prefixes: list[str] = Field(default_factory=list)
    regions: list[str] = Field(default_factory=list)
    keywords: list[str] = Field(default_factory=list)
    min_price: float | None = None
    max_price: float | None = None
    private_only: bool | None = None
    share_consent: bool | None = None
    niche_id: str | None = None


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


class SourceCredentialGuideOut(BaseModel):
    source: str
    display_name: str
    website: str
    signup_url: str | None = None
    steps: list[str] = Field(default_factory=list)
    url_hint: str | None = None
    env_names: list[str] = Field(default_factory=list)
    paid_note: str | None = None


class SourceCredentialOut(BaseModel):
    source: str
    label: str
    api_url: str | None = None
    token_configured: bool = False
    token_masked: str | None = None
    configured: bool = False
    url_from_db: bool = False
    token_from_db: bool = False
    updated_at: datetime | None = None
    guide: SourceCredentialGuideOut | None = None


class SourceCredentialIn(BaseModel):
    api_url: str | None = None
    api_token: str | None = Field(default=None, max_length=4096)
    clear_token: bool = False


class SourceCredentialTestIn(BaseModel):
    api_url: str | None = None
    api_token: str | None = Field(default=None, max_length=4096)


class SourceCredentialTestOut(BaseModel):
    ok: bool
    status_code: int | None = None
    detail: str


class ContractOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    external_id: str
    source: str
    law: str | None = None
    purchase_number: str | None = None
    title: str
    customer: str | None = None
    customer_inn: str | None = None
    supplier_name: str | None = None
    supplier_inn: str | None = None
    supplier_id: int | None = None
    region: str | None = None
    price: float | None = None
    nmck: float | None = None
    discount_pct: float | None = None
    currency: str = "RUB"
    status: str | None = None
    okpd2: str | None = None
    url: str
    description: str | None = None
    signed_at: datetime | None = None
    published_at: datetime | None = None
    tender_id: int | None = None


class ContractListResponse(BaseModel):
    items: list[ContractOut]
    total: int
    page: int
    page_size: int
    stats: dict[str, Any] = Field(default_factory=dict)


class SupplierOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    inn: str | None = None
    kpp: str | None = None
    name: str
    region: str | None = None
    win_count: int = 0
    total_contract_price: float = 0.0
    avg_contract_price: float | None = None
    avg_discount_pct: float | None = None
    last_won_at: datetime | None = None


class SupplierWinStatOut(BaseModel):
    supplier_inn: str | None = None
    supplier_name: str | None = None
    wins: int
    avg_price: float | None = None
    avg_discount_pct: float | None = None
    total_price: float | None = None
    last_won_at: datetime | None = None


class ContractAnalyticsOut(BaseModel):
    stats: dict[str, Any]
    top_suppliers: list[SupplierWinStatOut]


class MarketLookupIn(BaseModel):
    product: str = Field(min_length=2, max_length=500)
    city: str | None = None
    qty: float | None = None
    unit: str | None = None
    attrs: dict[str, Any] = Field(default_factory=dict)
    allow_stale: bool = False
    include_quarantined: bool = False
    private_only: bool | None = None
    niche_pilot: bool = True


class MarketOfferIn(BaseModel):
    source_type: str = "rfq"
    price_layer: str | None = None  # estimate|observed|firm
    supplier_name: str | None = None
    supplier_inn: str | None = None
    city_from: str | None = None
    city_to: str | None = None
    unit: str | None = None
    qty: float | None = None
    price_value: float | None = None
    currency: str = "RUB"
    vat: str | None = None
    delivery_price: float | None = None
    landed_unit_price: float | None = None
    lead_time_days: int | None = None
    payment_terms: str | None = None
    confidence: float = 0.7
    trust_score: float | None = None
    payload: dict[str, Any] = Field(default_factory=dict)


class MarketSaveIn(BaseModel):
    product: str = Field(min_length=2, max_length=500)
    city: str | None = None
    qty: float | None = None
    unit: str | None = None
    attrs: dict[str, Any] = Field(default_factory=dict)
    query_raw: str | None = None
    share_consent: bool = False
    summary: dict[str, Any] = Field(default_factory=dict)
    offers: list[MarketOfferIn] = Field(default_factory=list)


class MarketLookupOut(BaseModel):
    hit: bool
    reason: str
    fingerprint: str
    match_type: str | None = None
    meta: dict[str, Any] = Field(default_factory=dict)
    summary: dict[str, Any] | None = None
    offers: list[dict[str, Any]] = Field(default_factory=list)
    quarantine_offers: list[dict[str, Any]] = Field(default_factory=list)
    offer_count: int | None = None
    hit_count: int | None = None
    token_saved_estimate: int | None = None
    tokens_saved_this_hit: int | None = None
    expires_at: datetime | None = None
    updated_at: datetime | None = None
    freshness: str | None = None
    age_days: float | None = None
    ttl_days: int | None = None
    warning: str | None = None
    price_layers_note: str | None = None
    orchestration: dict[str, Any] | None = None
    anonymized: bool | None = None


class ClientSupplierIn(BaseModel):
    name: str = Field(min_length=1, max_length=500)
    supplier_inn: str | None = None
    contacts: dict[str, Any] = Field(default_factory=dict)
    notes: str | None = None
    tags: list[str] = Field(default_factory=list)


class ClientSupplierOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    supplier_inn: str | None = None
    contacts: dict[str, Any] | None = None
    notes: str | None = None
    tags: list[Any] = Field(default_factory=list)
    updated_at: datetime | None = None


class RfqCreateIn(BaseModel):
    product: str = Field(min_length=2, max_length=500)
    city: str | None = "Москва"
    qty: float | None = None
    unit: str | None = "шт"
    attrs: dict[str, Any] = Field(default_factory=dict)
    notes: str | None = None
    max_cold: int | None = Field(default=None, ge=0, le=30)


class RfqOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    product: str
    city: str
    qty: float | None = None
    unit: str | None = None
    attrs: dict[str, Any] | None = None
    fingerprint: str
    status: str
    form_token: str
    form_url: str | None = None
    max_cold_targets: int = 6
    share_consent: bool = False
    private_only: bool = False
    sent_at: datetime | None = None
    created_at: datetime | None = None
    targets_count: int | None = None


class RfqFormSubmitIn(BaseModel):
    supplier_name: str = Field(min_length=1, max_length=500)
    supplier_inn: str | None = None
    unit: str | None = None
    qty: float | None = None
    price_value: float | None = None
    currency: str = "RUB"
    vat: str | None = None
    delivery_price: float | None = None
    lead_time_days: int | None = None
    payment_terms: str | None = None
    city_from: str | None = None
    raw_message: str | None = None


class RfqDealConfirmIn(BaseModel):
    rfq_id: int
    supplier_inn: str | None = None
    supplier_name: str | None = None
    offer_id: int | None = None
    accepted_risk: bool = False
    checklist: dict[str, bool] = Field(default_factory=dict)


class ExecutionFeedbackIn(BaseModel):
    confirmation_id: int
    delivered_on_time: bool | None = None
    quality_ok: bool | None = None
    actual_price: float | None = None
    incident: bool = False
    notes: str | None = None

