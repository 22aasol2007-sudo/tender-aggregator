from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class User(Base):
    __tablename__ = "users"
    __table_args__ = (UniqueConstraint("email", name="uq_users_email"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(255), nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    name: Mapped[str] = mapped_column(String(120), default="Пользователь")
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False)
    telegram_chat_id: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    profile: Mapped[CompanyProfile | None] = relationship(back_populates="user", uselist=False)
    watches: Mapped[list[TenderWatch]] = relationship(back_populates="user")
    saved_searches: Mapped[list[SavedSearch]] = relationship(back_populates="user")


class CompanyProfile(Base):
    __tablename__ = "company_profiles"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), unique=True, nullable=False)
    company_name: Mapped[str | None] = mapped_column(String(255))
    okpd_prefixes: Mapped[list] = mapped_column(JSON, default=list)
    regions: Mapped[list] = mapped_column(JSON, default=list)
    keywords: Mapped[list] = mapped_column(JSON, default=list)
    min_price: Mapped[float | None] = mapped_column(Float)
    max_price: Mapped[float | None] = mapped_column(Float)
    private_only: Mapped[bool] = mapped_column(Boolean, default=False)
    share_consent: Mapped[bool] = mapped_column(Boolean, default=False)
    niche_id: Mapped[str | None] = mapped_column(String(64), default="cosmetics_moscow_gofra")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    user: Mapped[User] = relationship(back_populates="profile")


class Tender(Base):
    __tablename__ = "tenders"
    __table_args__ = (
        UniqueConstraint("source", "external_id", name="uq_source_external"),
        Index("ix_tenders_published_at", "published_at"),
        Index("ix_tenders_price", "price"),
        Index("ix_tenders_fingerprint", "fingerprint"),
        Index("ix_tenders_status_norm", "status_norm"),
        Index("ix_tenders_region", "region"),
        Index("ix_tenders_okpd2", "okpd2"),
        Index("ix_tenders_method", "method"),
        Index("ix_tenders_deadline_at", "deadline_at"),
        Index("ix_tenders_content_hash", "content_hash"),
        Index("ix_tenders_source_published", "source", "published_at"),
        Index("ix_tenders_status_published", "status_norm", "published_at"),
        Index("ix_tenders_region_status", "region", "status_norm"),
        Index("ix_tenders_dup_published", "is_duplicate", "published_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    external_id: Mapped[str] = mapped_column(String(64), nullable=False)
    source: Mapped[str] = mapped_column(String(32), nullable=False)
    law: Mapped[str | None] = mapped_column(String(16))
    title: Mapped[str] = mapped_column(Text, nullable=False)
    customer: Mapped[str | None] = mapped_column(Text)
    customer_inn: Mapped[str | None] = mapped_column(String(16))
    region: Mapped[str | None] = mapped_column(String(128))
    price: Mapped[float | None] = mapped_column(Float)
    currency: Mapped[str] = mapped_column(String(8), default="RUB")
    status: Mapped[str | None] = mapped_column(String(64))
    status_norm: Mapped[str] = mapped_column(String(32), default="unknown")
    method: Mapped[str | None] = mapped_column(String(128))
    okpd2: Mapped[str | None] = mapped_column(String(32))
    url: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    documents: Mapped[list | None] = mapped_column(JSON, default=list)
    lots: Mapped[list | None] = mapped_column(JSON, default=list)
    fingerprint: Mapped[str | None] = mapped_column(String(64))
    content_hash: Mapped[str | None] = mapped_column(String(64))
    is_duplicate: Mapped[bool] = mapped_column(Boolean, default=False)
    duplicate_of_id: Mapped[int | None] = mapped_column(Integer)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    deadline_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    enriched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    scraped_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    changed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    customer_id: Mapped[int | None] = mapped_column(ForeignKey("customers.id"), index=True)
    customer_kpp: Mapped[str | None] = mapped_column(String(16))

    changes: Mapped[list[TenderChange]] = relationship(back_populates="tender")
    customer_ref: Mapped[Customer | None] = relationship(back_populates="tenders")


class Customer(Base):
    __tablename__ = "customers"
    __table_args__ = (
        UniqueConstraint("inn", name="uq_customers_inn"),
        Index("ix_customers_name_norm", "name_normalized"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    inn: Mapped[str | None] = mapped_column(String(16))
    kpp: Mapped[str | None] = mapped_column(String(16))
    name: Mapped[str] = mapped_column(Text, nullable=False)
    name_normalized: Mapped[str] = mapped_column(String(512), nullable=False)
    holding_name: Mapped[str | None] = mapped_column(String(255))
    region: Mapped[str | None] = mapped_column(String(128))
    tender_count: Mapped[int] = mapped_column(Integer, default=0)
    total_price: Mapped[float] = mapped_column(Float, default=0.0)
    in_rnp: Mapped[bool] = mapped_column(Boolean, default=False)
    has_bank_guarantee: Mapped[bool | None] = mapped_column(Boolean)
    compliance_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    compliance_notes: Mapped[str | None] = mapped_column(Text)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    tenders: Mapped[list[Tender]] = relationship(back_populates="customer_ref")


class SourceHealth(Base):
    __tablename__ = "source_health"

    id: Mapped[int] = mapped_column(primary_key=True)
    source: Mapped[str] = mapped_column(String(32), unique=True, nullable=False)
    display_name: Mapped[str | None] = mapped_column(String(128))
    last_status: Mapped[str] = mapped_column(String(32), default="unknown")
    last_ok_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(Text)
    success_count: Mapped[int] = mapped_column(Integer, default=0)
    fallback_count: Mapped[int] = mapped_column(Integer, default=0)
    error_count: Mapped[int] = mapped_column(Integer, default=0)
    empty_count: Mapped[int] = mapped_column(Integer, default=0)
    consecutive_failures: Mapped[int] = mapped_column(Integer, default=0)
    last_fetched: Mapped[int] = mapped_column(Integer, default=0)
    last_upserted: Mapped[int] = mapped_column(Integer, default=0)
    silence_alerted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class WorkerJob(Base):
    __tablename__ = "worker_jobs"
    __table_args__ = (
        Index("ix_worker_jobs_status", "status"),
        Index("ix_worker_jobs_priority", "status", "priority"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    job_type: Mapped[str] = mapped_column(String(64), nullable=False)  # scrape|enrich|monitor
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    priority: Mapped[int] = mapped_column(Integer, default=100)  # lower = sooner
    status: Mapped[str] = mapped_column(String(32), default="pending")  # pending|running|done|failed
    result: Mapped[dict | None] = mapped_column(JSON)
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class TenderChange(Base):
    __tablename__ = "tender_changes"
    __table_args__ = (Index("ix_tender_changes_tender_id", "tender_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    tender_id: Mapped[int] = mapped_column(ForeignKey("tenders.id"), nullable=False)
    field: Mapped[str] = mapped_column(String(64), nullable=False)
    old_value: Mapped[str | None] = mapped_column(Text)
    new_value: Mapped[str | None] = mapped_column(Text)
    changed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    tender: Mapped[Tender] = relationship(back_populates="changes")


class TenderWatch(Base):
    __tablename__ = "tender_watches"
    __table_args__ = (UniqueConstraint("user_id", "tender_id", name="uq_user_tender_watch"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    tender_id: Mapped[int] = mapped_column(ForeignKey("tenders.id"), nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="favorite")  # favorite|in_work|done
    notes: Mapped[str | None] = mapped_column(Text)
    tags: Mapped[list] = mapped_column(JSON, default=list)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    user: Mapped[User] = relationship(back_populates="watches")


class SavedSearch(Base):
    __tablename__ = "saved_searches"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    filters: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    last_seen_ids: Mapped[list] = mapped_column(JSON, default=list)
    new_count: Mapped[int] = mapped_column(Integer, default=0)
    notify_telegram: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    user: Mapped[User] = relationship(back_populates="saved_searches")


class FilterPreset(Base):
    __tablename__ = "filter_presets"
    __table_args__ = (UniqueConstraint("name", "user_id", name="uq_preset_name_user"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    filters: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    is_builtin: Mapped[bool] = mapped_column(Boolean, default=False)
    is_shared: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ScrapeRun(Base):
    __tablename__ = "scrape_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    source: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    fetched: Mapped[int] = mapped_column(default=0)
    upserted: Mapped[int] = mapped_column(default=0)
    skipped: Mapped[int] = mapped_column(default=0)
    error: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class SourceApiCredential(Base):
    """Admin-managed API URL/token overrides for commercial scrape sources.

    Non-empty DB values win over env vars (CONTOUR_API_* etc.).
    """

    __tablename__ = "source_api_credentials"
    __table_args__ = (UniqueConstraint("source", name="uq_source_api_credentials_source"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    source: Mapped[str] = mapped_column(String(32), nullable=False)
    api_url: Mapped[str | None] = mapped_column(Text)
    api_token: Mapped[str | None] = mapped_column(Text)
    updated_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Supplier(Base):
    """Winner / contractor from concluded contracts (not the buyer)."""

    __tablename__ = "suppliers"
    __table_args__ = (
        UniqueConstraint("inn", name="uq_suppliers_inn"),
        Index("ix_suppliers_name_norm", "name_normalized"),
        Index("ix_suppliers_wins", "win_count"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    inn: Mapped[str | None] = mapped_column(String(16))
    kpp: Mapped[str | None] = mapped_column(String(16))
    name: Mapped[str] = mapped_column(Text, nullable=False)
    name_normalized: Mapped[str] = mapped_column(String(512), nullable=False)
    region: Mapped[str | None] = mapped_column(String(128))
    win_count: Mapped[int] = mapped_column(Integer, default=0)
    total_contract_price: Mapped[float] = mapped_column(Float, default=0.0)
    avg_contract_price: Mapped[float | None] = mapped_column(Float)
    avg_discount_pct: Mapped[float | None] = mapped_column(Float)
    last_won_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    contracts: Mapped[list[Contract]] = relationship(back_populates="supplier_ref")


class Contract(Base):
    """Concluded contract / award from EIS registry (price = actual award, not NMCK)."""

    __tablename__ = "contracts"
    __table_args__ = (
        UniqueConstraint("source", "external_id", name="uq_contracts_source_external"),
        Index("ix_contracts_signed_at", "signed_at"),
        Index("ix_contracts_price", "price"),
        Index("ix_contracts_region", "region"),
        Index("ix_contracts_okpd2", "okpd2"),
        Index("ix_contracts_supplier_id", "supplier_id"),
        Index("ix_contracts_purchase_number", "purchase_number"),
        Index("ix_contracts_law_signed", "law", "signed_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    external_id: Mapped[str] = mapped_column(String(64), nullable=False)
    source: Mapped[str] = mapped_column(String(32), nullable=False)  # eis_contract_44 | eis_contract_223
    law: Mapped[str | None] = mapped_column(String(16))
    purchase_number: Mapped[str | None] = mapped_column(String(64))
    title: Mapped[str] = mapped_column(Text, nullable=False)
    customer: Mapped[str | None] = mapped_column(Text)
    customer_inn: Mapped[str | None] = mapped_column(String(16))
    supplier_name: Mapped[str | None] = mapped_column(Text)
    supplier_inn: Mapped[str | None] = mapped_column(String(16))
    supplier_id: Mapped[int | None] = mapped_column(ForeignKey("suppliers.id"))
    region: Mapped[str | None] = mapped_column(String(128))
    price: Mapped[float | None] = mapped_column(Float)  # contract / award price
    nmck: Mapped[float | None] = mapped_column(Float)  # notice max price when known
    discount_pct: Mapped[float | None] = mapped_column(Float)  # (nmck-price)/nmck*100
    currency: Mapped[str] = mapped_column(String(8), default="RUB")
    status: Mapped[str | None] = mapped_column(String(64))
    okpd2: Mapped[str | None] = mapped_column(String(32))
    url: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    search_text: Mapped[str | None] = mapped_column(Text)
    signed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    tender_id: Mapped[int | None] = mapped_column(ForeignKey("tenders.id"), index=True)
    scraped_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    supplier_ref: Mapped[Supplier | None] = relationship(back_populates="contracts")
    tender_ref: Mapped[Tender | None] = relationship()


class MarketQueryCache(Base):
    """Cross-client cache of normalized sourcing queries (shared market intelligence)."""

    __tablename__ = "market_query_cache"
    __table_args__ = (
        UniqueConstraint("fingerprint", name="uq_market_query_fingerprint"),
        Index("ix_market_query_expires", "expires_at"),
        Index("ix_market_query_category_city", "category_key", "city_key"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    category_key: Mapped[str] = mapped_column(String(128), nullable=False)
    city_key: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    qty_band: Mapped[str] = mapped_column(String(32), default="unknown")
    unit: Mapped[str | None] = mapped_column(String(32))
    query_raw: Mapped[str | None] = mapped_column(Text)
    result_summary: Mapped[dict | None] = mapped_column(JSON, default=dict)
    offer_count: Mapped[int] = mapped_column(Integer, default=0)
    hit_count: Mapped[int] = mapped_column(Integer, default=0)
    token_saved_estimate: Mapped[int] = mapped_column(Integer, default=0)
    source_mix: Mapped[dict | None] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    offers: Mapped[list[MarketOfferObservation]] = relationship(back_populates="query_cache")


class MarketOfferObservation(Base):
    """Anonymized offer / KP snapshot reusable across clients."""

    __tablename__ = "market_offer_observations"
    __table_args__ = (
        Index("ix_market_offer_fingerprint", "fingerprint"),
        Index("ix_market_offer_observed", "observed_at"),
        Index("ix_market_offer_supplier_inn", "supplier_inn"),
        Index("ix_market_offer_query_id", "query_cache_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    fingerprint: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    query_cache_id: Mapped[int | None] = mapped_column(ForeignKey("market_query_cache.id"))
    source_type: Mapped[str] = mapped_column(String(32), nullable=False)  # rfq|contract|manual|estimate|firm_rfq
    price_layer: Mapped[str] = mapped_column(String(16), default="observed")  # estimate|observed|firm
    trust_score: Mapped[float] = mapped_column(Float, default=0.7)
    quarantined: Mapped[bool] = mapped_column(Boolean, default=False)
    quarantine_reason: Mapped[str | None] = mapped_column(String(64))
    shareable: Mapped[bool] = mapped_column(Boolean, default=False)
    incomparable: Mapped[bool] = mapped_column(Boolean, default=False)
    owner_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))  # private firm / private-only
    supplier_name: Mapped[str | None] = mapped_column(Text)
    supplier_inn: Mapped[str | None] = mapped_column(String(16))
    city_from: Mapped[str | None] = mapped_column(String(128))
    city_to: Mapped[str | None] = mapped_column(String(128))
    unit: Mapped[str | None] = mapped_column(String(32))
    qty: Mapped[float | None] = mapped_column(Float)
    price_value: Mapped[float | None] = mapped_column(Float)
    currency: Mapped[str] = mapped_column(String(8), default="RUB")
    vat: Mapped[str | None] = mapped_column(String(32))
    delivery_price: Mapped[float | None] = mapped_column(Float)
    landed_unit_price: Mapped[float | None] = mapped_column(Float)
    lead_time_days: Mapped[int | None] = mapped_column(Integer)
    payment_terms: Mapped[str | None] = mapped_column(String(128))
    confidence: Mapped[float] = mapped_column(Float, default=0.7)
    payload: Mapped[dict | None] = mapped_column(JSON, default=dict)  # sanitized fields only
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    query_cache: Mapped[MarketQueryCache | None] = relationship(back_populates="offers")


class ClientSupplierBook(Base):
    """Private per-user supplier list — NEVER shared across clients."""

    __tablename__ = "client_supplier_books"
    __table_args__ = (
        UniqueConstraint("user_id", "supplier_inn", "name_normalized", name="uq_client_supplier"),
        Index("ix_client_supplier_user", "user_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    name_normalized: Mapped[str] = mapped_column(String(512), nullable=False)
    supplier_inn: Mapped[str | None] = mapped_column(String(16))
    contacts: Mapped[dict | None] = mapped_column(JSON, default=dict)
    notes: Mapped[str | None] = mapped_column(Text)
    tags: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class RfqRequest(Base):
    __tablename__ = "rfq_requests"
    __table_args__ = (
        Index("ix_rfq_user", "user_id"),
        Index("ix_rfq_fingerprint", "fingerprint"),
        Index("ix_rfq_form_token", "form_token"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    product: Mapped[str] = mapped_column(Text, nullable=False)
    city: Mapped[str] = mapped_column(String(128), default="Москва")
    qty: Mapped[float | None] = mapped_column(Float)
    unit: Mapped[str | None] = mapped_column(String(32))
    attrs: Mapped[dict | None] = mapped_column(JSON, default=dict)
    fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="draft")
    notes: Mapped[str | None] = mapped_column(Text)
    form_token: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    max_cold_targets: Mapped[int] = mapped_column(Integer, default=6)
    share_consent: Mapped[bool] = mapped_column(Boolean, default=False)
    private_only: Mapped[bool] = mapped_column(Boolean, default=False)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    targets: Mapped[list[RfqTarget]] = relationship(back_populates="rfq")


class RfqTarget(Base):
    __tablename__ = "rfq_targets"
    __table_args__ = (Index("ix_rfq_targets_rfq", "rfq_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    rfq_id: Mapped[int] = mapped_column(ForeignKey("rfq_requests.id"), nullable=False)
    source: Mapped[str] = mapped_column(String(32), default="manual")
    supplier_name: Mapped[str | None] = mapped_column(Text)
    supplier_inn: Mapped[str | None] = mapped_column(String(16))
    contact_email: Mapped[str | None] = mapped_column(String(255))
    contact_phone: Mapped[str | None] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(32), default="queued")
    warm: Mapped[bool] = mapped_column(Boolean, default=False)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    responded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    response_payload: Mapped[dict | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    rfq: Mapped[RfqRequest] = relationship(back_populates="targets")


class RfqDealConfirmation(Base):
    __tablename__ = "rfq_deal_confirmations"
    __table_args__ = (Index("ix_rfq_deal_user", "user_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    rfq_id: Mapped[int] = mapped_column(ForeignKey("rfq_requests.id"), nullable=False)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    offer_id: Mapped[int | None] = mapped_column(ForeignKey("market_offer_observations.id"))
    supplier_name: Mapped[str | None] = mapped_column(Text)
    supplier_inn: Mapped[str | None] = mapped_column(String(16))
    price_layer: Mapped[str] = mapped_column(String(16), default="firm")
    accepted_risk: Mapped[bool] = mapped_column(Boolean, default=False)
    checklist: Mapped[dict | None] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(32), default="confirmed")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class SourcingExecutionFeedback(Base):
    """Post-deal reality vs quote — core data moat."""

    __tablename__ = "sourcing_execution_feedback"
    __table_args__ = (Index("ix_exec_feedback_supplier", "supplier_inn"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    confirmation_id: Mapped[int] = mapped_column(ForeignKey("rfq_deal_confirmations.id"), nullable=False)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    supplier_inn: Mapped[str | None] = mapped_column(String(16))
    delivered_on_time: Mapped[bool | None] = mapped_column(Boolean)
    quality_ok: Mapped[bool | None] = mapped_column(Boolean)
    actual_price: Mapped[float | None] = mapped_column(Float)
    incident: Mapped[bool] = mapped_column(Boolean, default=False)
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
