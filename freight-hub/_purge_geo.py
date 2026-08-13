"""Delete loads outside Moscow corridor: near<=150 AND far<=1500."""
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
    near, far = 150.0, 1500.0
    db = HubDB(Path(config.DB_PATH))
    await db.connect()
    cur = await db.db.execute("SELECT COUNT(*) FROM loads")
    before = (await cur.fetchone())[0]
    # Missing km or outside corridor
    await db.db.execute(
        """
        DELETE FROM loads WHERE
          km_from IS NULL OR km_to IS NULL
          OR MIN(km_from, km_to) > ?
          OR MAX(km_from, km_to) > ?
        """,
        (near, far),
    )
    await db.db.commit()
    cur = await db.db.execute("SELECT COUNT(*) FROM loads")
    after = (await cur.fetchone())[0]
    print(f"before={before} after={after} deleted={before - after}")
    await db.close()


if __name__ == "__main__":
    asyncio.run(main())
