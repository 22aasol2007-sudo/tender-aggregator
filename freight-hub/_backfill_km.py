"""One-shot: verify WAL + backfill km_from/km_to for recent rows."""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT.parent))
sys.path.insert(0, str(ROOT))

from app import config
from app.db import HubDB
from freight_core.geo import distance_km


async def main() -> None:
    db = HubDB(Path(config.DB_PATH))
    await db.connect()
    cur = await db.db.execute("PRAGMA journal_mode")
    print("journal_mode", (await cur.fetchone())[0])
    cur = await db.db.execute(
        "SELECT id, from_city, to_city FROM loads "
        "WHERE (from_city IS NOT NULL OR to_city IS NOT NULL) "
        "AND (km_from IS NULL OR km_to IS NULL) "
        "ORDER BY scraped_at DESC LIMIT 5000"
    )
    rows = await cur.fetchall()
    for r in rows:
        kf = distance_km(r[1], "москва") if r[1] else None
        kt = distance_km(r[2], "москва") if r[2] else None
        await db.db.execute(
            "UPDATE loads SET km_from=?, km_to=? WHERE id=?",
            (kf, kt, r[0]),
        )
    await db.db.commit()
    print("backfilled", len(rows))
    h = await db.get_tg_health()
    print("tg", h.get("ok"), "resolved", h.get("resolved"), "note", h.get("note"))
    mx = await db.get_setting("max_health")
    print("max_health", mx[:200] if isinstance(mx, str) else mx)
    await db.close()


if __name__ == "__main__":
    asyncio.run(main())
