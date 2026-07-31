from __future__ import annotations

from collections.abc import Generator

from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import settings


def _make_engine(url: str) -> Engine:
    if url.startswith("sqlite"):
        return create_engine(url, connect_args={"check_same_thread": False}, pool_pre_ping=True)
    return create_engine(
        url,
        pool_pre_ping=True,
        pool_size=settings.db_pool_size,
        max_overflow=settings.db_max_overflow,
        connect_args={"connect_timeout": settings.db_connect_timeout},
    )


def _resolve_engine() -> Engine:
    primary = _make_engine(settings.database_url)
    try:
        with primary.connect() as conn:
            conn.execute(text("SELECT 1"))
        return primary
    except Exception:
        if settings.database_url.startswith("sqlite"):
            raise
        if not settings.allow_sqlite_fallback:
            raise
        return _make_engine(settings.sqlite_fallback_url)


engine = _resolve_engine()


@event.listens_for(engine, "connect")
def set_sqlite_pragma(dbapi_connection, connection_record) -> None:  # noqa: ARG001
    if engine.url.get_backend_name() == "sqlite":
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()


SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


def is_postgres() -> bool:
    return engine.url.get_backend_name().startswith("postgresql")


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def _ensure_composite_indexes() -> None:
    stmts = [
        "CREATE INDEX IF NOT EXISTS ix_tenders_source_published ON tenders (source, published_at DESC)",
        "CREATE INDEX IF NOT EXISTS ix_tenders_status_published ON tenders (status_norm, published_at DESC)",
        "CREATE INDEX IF NOT EXISTS ix_tenders_region_status ON tenders (region, status_norm)",
        "CREATE INDEX IF NOT EXISTS ix_tenders_dup_published ON tenders (is_duplicate, published_at DESC)",
        "CREATE INDEX IF NOT EXISTS ix_tenders_customer_id_pub ON tenders (customer_id, published_at DESC)",
        "CREATE INDEX IF NOT EXISTS ix_worker_jobs_claim ON worker_jobs (status, priority ASC, id ASC)",
    ]
    with engine.begin() as conn:
        for stmt in stmts:
            try:
                conn.execute(text(stmt))
            except Exception:  # noqa: BLE001
                # SQLite may lack DESC in older forms; ignore soft failures
                pass


def _ensure_postgres_fts() -> None:
    if not is_postgres():
        return
    stmts = [
        """
        ALTER TABLE tenders
        ADD COLUMN IF NOT EXISTS search_vector tsvector
        """,
        """
        CREATE INDEX IF NOT EXISTS ix_tenders_search_vector
        ON tenders USING GIN (search_vector)
        """,
        """
        CREATE OR REPLACE FUNCTION tenders_search_vector_update() RETURNS trigger AS $$
        BEGIN
          NEW.search_vector :=
            setweight(to_tsvector('russian', coalesce(NEW.title, '')), 'A') ||
            setweight(to_tsvector('russian', coalesce(NEW.customer, '')), 'B') ||
            setweight(to_tsvector('russian', coalesce(NEW.description, '')), 'C') ||
            setweight(to_tsvector('russian', coalesce(NEW.okpd2, '')), 'B') ||
            setweight(to_tsvector('russian', coalesce(NEW.region, '')), 'C') ||
            setweight(to_tsvector('russian', coalesce(NEW.method, '')), 'C') ||
            setweight(to_tsvector('russian', coalesce(NEW.external_id, '')), 'A');
          RETURN NEW;
        END
        $$ LANGUAGE plpgsql
        """,
        """
        DROP TRIGGER IF EXISTS tenders_search_vector_trigger ON tenders
        """,
        """
        CREATE TRIGGER tenders_search_vector_trigger
        BEFORE INSERT OR UPDATE OF title, customer, description, okpd2, region, method, external_id
        ON tenders
        FOR EACH ROW EXECUTE PROCEDURE tenders_search_vector_update()
        """,
        """
        UPDATE tenders SET title = title WHERE search_vector IS NULL
        """,
    ]
    with engine.begin() as conn:
        for stmt in stmts:
            conn.execute(text(stmt))


def _migrate_sqlite_columns() -> None:
    if engine.url.get_backend_name() != "sqlite":
        return
    needed = {
        "customer_inn": "ALTER TABLE tenders ADD COLUMN customer_inn VARCHAR(16)",
        "status_norm": "ALTER TABLE tenders ADD COLUMN status_norm VARCHAR(32) DEFAULT 'unknown'",
        "okpd2": "ALTER TABLE tenders ADD COLUMN okpd2 VARCHAR(32)",
        "documents": "ALTER TABLE tenders ADD COLUMN documents JSON",
        "lots": "ALTER TABLE tenders ADD COLUMN lots JSON",
        "fingerprint": "ALTER TABLE tenders ADD COLUMN fingerprint VARCHAR(64)",
        "content_hash": "ALTER TABLE tenders ADD COLUMN content_hash VARCHAR(64)",
        "is_duplicate": "ALTER TABLE tenders ADD COLUMN is_duplicate BOOLEAN DEFAULT 0",
        "duplicate_of_id": "ALTER TABLE tenders ADD COLUMN duplicate_of_id INTEGER",
        "enriched_at": "ALTER TABLE tenders ADD COLUMN enriched_at DATETIME",
        "changed_at": "ALTER TABLE tenders ADD COLUMN changed_at DATETIME",
        "customer_id": "ALTER TABLE tenders ADD COLUMN customer_id INTEGER",
        "customer_kpp": "ALTER TABLE tenders ADD COLUMN customer_kpp VARCHAR(16)",
    }
    with engine.begin() as conn:
        rows = conn.execute(text("PRAGMA table_info(tenders)")).fetchall()
        if not rows:
            return
        existing = {r[1] for r in rows}
        for col, stmt in needed.items():
            if col not in existing:
                conn.execute(text(stmt))

        preset_cols = conn.execute(text("PRAGMA table_info(filter_presets)")).fetchall()
        if preset_cols:
            pexisting = {r[1] for r in preset_cols}
            if "user_id" not in pexisting:
                conn.execute(text("ALTER TABLE filter_presets ADD COLUMN user_id INTEGER"))
            if "is_shared" not in pexisting:
                conn.execute(text("ALTER TABLE filter_presets ADD COLUMN is_shared BOOLEAN DEFAULT 0"))

        scrape_cols = conn.execute(text("PRAGMA table_info(scrape_runs)")).fetchall()
        if scrape_cols:
            sexisting = {r[1] for r in scrape_cols}
            if "skipped" not in sexisting:
                conn.execute(text("ALTER TABLE scrape_runs ADD COLUMN skipped INTEGER DEFAULT 0"))

        job_cols = conn.execute(text("PRAGMA table_info(worker_jobs)")).fetchall()
        if job_cols:
            jexisting = {r[1] for r in job_cols}
            if "priority" not in jexisting:
                conn.execute(text("ALTER TABLE worker_jobs ADD COLUMN priority INTEGER DEFAULT 100"))


def _migrate_postgres_columns() -> None:
    if not is_postgres():
        return
    stmts = [
        "ALTER TABLE worker_jobs ADD COLUMN IF NOT EXISTS priority INTEGER DEFAULT 100",
        "ALTER TABLE tenders ADD COLUMN IF NOT EXISTS customer_inn VARCHAR(16)",
        "ALTER TABLE tenders ADD COLUMN IF NOT EXISTS status_norm VARCHAR(32) DEFAULT 'unknown'",
        "ALTER TABLE tenders ADD COLUMN IF NOT EXISTS okpd2 VARCHAR(32)",
        "ALTER TABLE tenders ADD COLUMN IF NOT EXISTS documents JSONB",
        "ALTER TABLE tenders ADD COLUMN IF NOT EXISTS lots JSONB",
        "ALTER TABLE tenders ADD COLUMN IF NOT EXISTS fingerprint VARCHAR(64)",
        "ALTER TABLE tenders ADD COLUMN IF NOT EXISTS content_hash VARCHAR(64)",
        "ALTER TABLE tenders ADD COLUMN IF NOT EXISTS is_duplicate BOOLEAN DEFAULT FALSE",
        "ALTER TABLE tenders ADD COLUMN IF NOT EXISTS duplicate_of_id INTEGER",
        "ALTER TABLE tenders ADD COLUMN IF NOT EXISTS enriched_at TIMESTAMPTZ",
        "ALTER TABLE tenders ADD COLUMN IF NOT EXISTS changed_at TIMESTAMPTZ",
        "ALTER TABLE tenders ADD COLUMN IF NOT EXISTS customer_id INTEGER",
        "ALTER TABLE tenders ADD COLUMN IF NOT EXISTS customer_kpp VARCHAR(16)",
        "ALTER TABLE filter_presets ADD COLUMN IF NOT EXISTS user_id INTEGER",
        "ALTER TABLE filter_presets ADD COLUMN IF NOT EXISTS is_shared BOOLEAN DEFAULT FALSE",
        "ALTER TABLE scrape_runs ADD COLUMN IF NOT EXISTS skipped INTEGER DEFAULT 0",
    ]
    with engine.begin() as conn:
        for stmt in stmts:
            conn.execute(text(stmt))


def init_db() -> None:
    from pathlib import Path

    from app import models  # noqa: F401

    if engine.url.get_backend_name() == "sqlite":
        db_path = str(engine.url.database or "")
        if db_path:
            Path(db_path).parent.mkdir(parents=True, exist_ok=True)

    Base.metadata.create_all(bind=engine)
    _migrate_sqlite_columns()
    _migrate_postgres_columns()
    _ensure_composite_indexes()
    _ensure_postgres_fts()
