"""Re-parse recent TG/MAX rows with missing/bad routes."""
from __future__ import annotations

import asyncio
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT.parent))
sys.path.insert(0, str(ROOT))

from app import config
from app.db import HubDB, make_fingerprint, make_route_fingerprint
from freight_core.geo import distance_km
from freight_core.parse import parse_load


BAD_FROM = {"готов", "готова", "готово", "задняя", "реально", "рубцовский", "обл"}


async def main() -> None:
    db = HubDB(Path(config.DB_PATH))
    await db.connect()
    now = time.time()
    cur = await db.db.execute(
        """
        SELECT id, source, external_id, body, from_city, to_city, tonnage, score
        FROM loads
        WHERE source IN ('telegram','max')
          AND scraped_at >= ?
          AND (
            IFNULL(from_city,'')='' OR IFNULL(to_city,'')=''
            OR lower(from_city) IN ('готов','готова','готово','задняя','реально')
            OR lower(to_city) IN ('готов','готова','готово','задняя','реально')
            OR title LIKE '%?%'
          )
        ORDER BY scraped_at DESC
        LIMIT 8000
        """,
        (now - 3 * 86400,),
    )
    rows = await cur.fetchall()
    fixed = 0
    for r in rows:
        p = parse_load(r[3] or "")
        frm, to = p.from_city, p.to_city
        if not frm and not to:
            continue
        old_a, old_b = (r[4] or "").lower(), (r[5] or "").lower()
        if frm == r[4] and to == r[5]:
            continue
        if (not frm or not to) and old_a and old_b and old_a not in BAD_FROM and old_b not in BAD_FROM:
            continue
        title = f"{frm or '?'} → {to or '?'}"
        tonnage = r[6] if r[6] is not None else p.tonnage
        fp = make_fingerprint(r[1], frm or "", to or "", str(tonnage or ""), (r[3] or "")[:200])
        route_fp = make_route_fingerprint(frm, to, tonnage, p.load_date)
        km_from = distance_km(frm, "москва") if frm else None
        km_to = distance_km(to, "москва") if to else None
        await db.db.execute(
            """
            UPDATE loads SET
              from_city=?, to_city=?, title=?,
              tonnage=COALESCE(tonnage, ?),
              body_type=COALESCE(body_type, ?),
              fingerprint=?, route_fp=?,
              km_from=?, km_to=?
            WHERE id=?
            """,
            (
                frm,
                to,
                title,
                tonnage,
                p.body,
                fp,
                route_fp,
                km_from,
                km_to,
                r[0],
            ),
        )
        fixed += 1
    await db.db.commit()
    print(f"scanned={len(rows)} fixed={fixed}")
    await db.close()


if __name__ == "__main__":
    asyncio.run(main())
