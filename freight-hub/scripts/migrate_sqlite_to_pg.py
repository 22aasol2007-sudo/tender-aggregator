#!/usr/bin/env python3
"""Export SQLite hub.db → Postgres/Neon (one-shot).

Usage:
  set DATABASE_URL=postgres://...
  set DB_PATH=data/hub.db
  python scripts/migrate_sqlite_to_pg.py

Does not switch the live app — set DATABASE_URL and deploy a Postgres HubDB later.
"""

from __future__ import annotations

import os
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main() -> int:
    db_url = (os.getenv("DATABASE_URL") or "").strip()
    if not db_url:
        print("DATABASE_URL required", file=sys.stderr)
        return 2
    sqlite_path = Path(os.getenv("DB_PATH", str(ROOT / "data" / "hub.db")))
    if not sqlite_path.exists():
        print(f"missing {sqlite_path}", file=sys.stderr)
        return 2

    try:
        import psycopg
    except ImportError:
        print("pip install psycopg[binary]", file=sys.stderr)
        return 2

    schema = (ROOT / "sql" / "schema_postgres.sql").read_text(encoding="utf-8")
    src = sqlite3.connect(str(sqlite_path))
    src.row_factory = sqlite3.Row

    with psycopg.connect(db_url) as dst:
        dst.execute(schema)
        # settings + tg_health
        for table in ("settings", "tg_health"):
            try:
                rows = src.execute(f"SELECT key, value FROM {table}").fetchall()
            except sqlite3.OperationalError:
                continue
            for r in rows:
                dst.execute(
                    f"INSERT INTO {table}(key, value) VALUES (%s,%s) "
                    f"ON CONFLICT (key) DO UPDATE SET value=EXCLUDED.value",
                    (r["key"], r["value"]),
                )
        # loads (core columns)
        cols = [
            "source", "external_id", "title", "body", "from_city", "to_city",
            "tonnage", "volume_m3", "body_type", "temps", "price", "load_date",
            "phones", "contacts", "url", "score", "score_ok", "kind",
            "fingerprint", "route_fp", "km_from", "km_to", "route_km",
            "price_per_km", "raw_json", "created_at", "scraped_at",
        ]
        qcols = ",".join(cols)
        placeholders = ",".join(["%s"] * len(cols))
        n = 0
        for r in src.execute(f"SELECT {qcols} FROM loads"):
            vals = [r[c] for c in cols]
            dst.execute(
                f"INSERT INTO loads ({qcols}) VALUES ({placeholders}) "
                f"ON CONFLICT (source, external_id) DO NOTHING",
                vals,
            )
            n += 1
            if n % 500 == 0:
                dst.commit()
                print("loads", n)
        dst.commit()
        print(f"done loads={n}")
    src.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
