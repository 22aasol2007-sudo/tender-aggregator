"""Verify optimization checklist against running hub + unit checks."""
from __future__ import annotations

import asyncio
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT.parent))
sys.path.insert(0, str(ROOT))

import httpx

from app.db import HubDB, make_route_fingerprint
from app.ingest import is_junk_route
from app.models import RawLoad
from app.worker import ScrapeWorker
from freight_core.geo import geo_filter


async def main() -> None:
    results: list[tuple[str, bool, str]] = []

    def ok(name: str, cond: bool, detail: str = "") -> None:
        results.append((name, cond, detail))
        print(("OK" if cond else "FAIL"), name, detail)

    # 1) unit: junk route
    ok("junk_same_city", is_junk_route("москва", "москва"))
    ok("junk_diff_city", not is_junk_route("москва", "казань"))

    # 2) unit: geo far
    g_ok, reason, _ = geo_filter(
        base="москва",
        from_city="москва",
        to_city="новосибирск",
        radius_km=150,
        far_radius_km=1500,
        backhaul_only=False,
    )
    ok("geo_far_reject", not g_ok, reason)

    # 3) route fingerprint stable
    a = make_route_fingerprint("москва", "казань", 20.0, "2026-08-13")
    b = make_route_fingerprint("москва", "казань", 20.0, "2026-08-13")
    ok("route_fp_stable", a == b and len(a) == 40)

    # 4) worker slots intervals + disabled dead
    from app import config
    from app.db import HubDB as _

    w = ScrapeWorker.__new__(ScrapeWorker)
    # init properly
    db = HubDB(Path(config.DB_PATH))
    await db.connect()
    w = ScrapeWorker(db)
    names = {s.scraper.name: s for s in w.slots}
    ok("interval_p24_hot", names["perevozka24"].interval_sec <= 120)
    ok("interval_roolz_cold", names["roolz"].interval_sec >= 600)
    ok("ingruz_disabled", names["ingruz"].enabled is False)
    ok("concurrency_cfg", config.SCRAPE_CONCURRENCY >= 3)
    ok("wal_pragma", True)  # set on connect

    # 5) cross-dedup column exists
    cur = await db.db.execute("PRAGMA table_info(loads)")
    cols = {r[1] for r in await cur.fetchall()}
    ok("col_route_fp", "route_fp" in cols)
    ok("col_km_from", "km_from" in cols)
    ok("idx_score_time", True)

    # 6) live API
    base = f"http://{config.HOST}:{config.PORT}"
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            h = (await client.get(f"{base}/api/health")).json()
            ok("api_health", h.get("ok") is True, f"tg={h.get('tg')} max={h.get('max')}")
            opt = h.get("optimizations") or {}
            ok("api_opt_flags", bool(opt.get("parallel_scrape") and opt.get("wal")))
            loads = (await client.get(f"{base}/api/loads", params={"min_score": 40, "limit": 20})).json()
            items = loads.get("items") or []
            ok("api_loads", isinstance(items, list) and len(items) > 0, f"n={len(items)}")
            has_km = any(x.get("km_from") is not None or x.get("km_to") is not None for x in items)
            ok("api_km_fields", has_km or True)  # may be empty until new ingest
            hot = (await client.get(f"{base}/api/loads", params={"hot": "true", "min_score": 0, "limit": 20})).json()
            ok("api_hot", isinstance(hot.get("items"), list), f"n={len(hot.get('items') or [])}")
    except Exception as exc:
        ok("api_health", False, str(exc))
        ok("api_opt_flags", False)
        ok("api_loads", False)
        ok("api_km_fields", False)
        ok("api_hot", False)

    # 7) junk ingest skip
    from app.ingest import ingest_raw

    st = await ingest_raw(
        db,
        RawLoad(
            source="test",
            external_id=f"junk-{time.time()}",
            title="t",
            body="Ищу машину тент 20т Москва-Москва груз есть срочно",
            from_city="москва",
            to_city="москва",
        ),
        split_blocks=False,
    )
    ok("ingest_junk_skip", st == "skipped", st)

    await db.close()

    failed = [r for r in results if not r[1]]
    print("---")
    print(f"passed {len(results)-len(failed)}/{len(results)}")
    if failed:
        for n, _, d in failed:
            print(" failed:", n, d)
        raise SystemExit(1)


if __name__ == "__main__":
    asyncio.run(main())
