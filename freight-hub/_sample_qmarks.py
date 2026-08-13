import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import config
from app.db import HubDB


async def main() -> None:
    db = HubDB(Path(config.DB_PATH))
    await db.connect()
    cur = await db.db.execute(
        """
        SELECT id, title, from_city, to_city, tonnage, body_type, score, kind, body
        FROM loads
        WHERE source='telegram'
          AND (IFNULL(from_city,'')='' OR IFNULL(to_city,'')='')
          AND score >= 40
        ORDER BY scraped_at DESC
        LIMIT 15
        """
    )
    for r in await cur.fetchall():
        print("---", r[0], "score", r[6], "t", r[4], r[5], r[7])
        print("title:", r[1])
        print("from/to:", r[2], "->", r[3])
        print((r[8] or "")[:600])
        print()
    await db.close()


if __name__ == "__main__":
    asyncio.run(main())
