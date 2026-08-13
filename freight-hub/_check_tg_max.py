"""Quick TG/MAX ingest + parse health."""
from __future__ import annotations

import asyncio
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT.parent))
sys.path.insert(0, str(ROOT))

from app import config
from app.db import HubDB


async def main() -> None:
    db = HubDB(Path(config.DB_PATH))
    await db.connect()
    now = time.time()
    for src in ("telegram", "max"):
        cur = await db.db.execute(
            "SELECT COUNT(*) FROM loads WHERE source=? AND scraped_at>=?",
            (src, now - 900),
        )
        n15 = (await cur.fetchone())[0]
        cur = await db.db.execute(
            "SELECT COUNT(*) FROM loads WHERE source=? AND scraped_at>=?",
            (src, now - 3600),
        )
        n60 = (await cur.fetchone())[0]
        cur = await db.db.execute(
            """
            SELECT COUNT(*) FROM loads
            WHERE source=? AND scraped_at>=?
              AND IFNULL(from_city,'')!='' AND IFNULL(to_city,'')!=''
            """,
            (src, now - 3600),
        )
        with_route = (await cur.fetchone())[0]
        cur = await db.db.execute(
            "SELECT COUNT(*) FROM loads WHERE source=? AND scraped_at>=? AND score>=40",
            (src, now - 3600),
        )
        score40 = (await cur.fetchone())[0]
        cur = await db.db.execute(
            """
            SELECT title, from_city, to_city, score, kind, scraped_at, substr(body,1,90)
            FROM loads WHERE source=? ORDER BY scraped_at DESC LIMIT 8
            """,
            (src,),
        )
        rows = await cur.fetchall()
        print(f"=== {src} ===")
        print(
            f"last15m={n15} last60m={n60} with_route_60m={with_route} "
            f"score>=40_60m={score40} route_pct={((100*with_route/n60) if n60 else 0):.0f}%"
        )
        for r in rows:
            age = int(now - r[5])
            body = (r[6] or "").replace("\n", " ")
            print(f"  {age:>5}s score={r[3]} kind={r[4]} {r[1]} -> {r[2]}")
            print(f"         {body}")
    for k in ("last_ingest_telegram", "last_ingest_max"):
        v = await db.get_setting(k)
        if not v:
            print(f"{k}: none")
            continue
        try:
            print(f"{k}: {int(now - float(v))}s ago")
        except Exception:
            print(f"{k}: {v}")
    await db.close()


if __name__ == "__main__":
    asyncio.run(main())
