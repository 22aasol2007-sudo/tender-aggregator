"""Delete messenger loads so backfill reloads only last MAX_LOAD_AGE_DAYS."""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT.parent))
sys.path.insert(0, str(ROOT))

from app import config
from app.db import HubDB


async def main() -> None:
    db = HubDB(Path(config.DB_PATH))
    await db.connect()
    cur = await db.db.execute("SELECT source, COUNT(*) AS n FROM loads GROUP BY source")
    print("before", {r[0]: r[1] for r in await cur.fetchall()})
    await db.db.execute("DELETE FROM loads WHERE source IN ('telegram','max','tg_public')")
    await db.db.commit()
    await db.cleanup_smart()
    cur = await db.db.execute("SELECT source, COUNT(*) AS n FROM loads GROUP BY source")
    print("after", {r[0]: r[1] for r in await cur.fetchall()})
    await db.close()


if __name__ == "__main__":
    asyncio.run(main())
