-- Postgres / Neon schema for Freight Hub (optional migration from SQLite)
-- Apply: psql "$DATABASE_URL" -f sql/schema_postgres.sql

CREATE TABLE IF NOT EXISTS loads (
    id BIGSERIAL PRIMARY KEY,
    source TEXT NOT NULL,
    external_id TEXT NOT NULL,
    title TEXT,
    body TEXT NOT NULL,
    from_city TEXT,
    to_city TEXT,
    tonnage DOUBLE PRECISION,
    volume_m3 DOUBLE PRECISION,
    body_type TEXT,
    temps TEXT,
    price TEXT,
    load_date TEXT,
    phones TEXT,
    contacts TEXT,
    url TEXT,
    score INTEGER NOT NULL DEFAULT 0,
    score_ok INTEGER NOT NULL DEFAULT 1,
    kind TEXT,
    fingerprint TEXT NOT NULL,
    route_fp TEXT,
    km_from DOUBLE PRECISION,
    km_to DOUBLE PRECISION,
    route_km DOUBLE PRECISION,
    price_per_km DOUBLE PRECISION,
    raw_json TEXT,
    created_at DOUBLE PRECISION NOT NULL,
    scraped_at DOUBLE PRECISION NOT NULL,
    UNIQUE (source, external_id)
);

CREATE INDEX IF NOT EXISTS idx_loads_scraped ON loads (scraped_at DESC);
CREATE INDEX IF NOT EXISTS idx_loads_score ON loads (score DESC);
CREATE INDEX IF NOT EXISTS idx_loads_fp ON loads (fingerprint);
CREATE INDEX IF NOT EXISTS idx_loads_route ON loads (from_city, to_city);
CREATE INDEX IF NOT EXISTS idx_loads_route_fp ON loads (route_fp);
CREATE INDEX IF NOT EXISTS idx_loads_score_time ON loads (score DESC, scraped_at DESC);

CREATE TABLE IF NOT EXISTS scrape_runs (
    id BIGSERIAL PRIMARY KEY,
    source TEXT NOT NULL,
    ok INTEGER NOT NULL,
    added INTEGER NOT NULL DEFAULT 0,
    updated INTEGER NOT NULL DEFAULT 0,
    error TEXT,
    started_at DOUBLE PRECISION NOT NULL,
    finished_at DOUBLE PRECISION NOT NULL
);

CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS tg_health (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
