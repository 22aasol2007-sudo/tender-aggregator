"""Post-scrape analysis: counts, geo corridor, sample routes."""
from __future__ import annotations

import sqlite3
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import app._bootstrap  # noqa: F401

from freight_core.geo import geo_filter

DB = Path(__file__).resolve().parent / "data" / "hub.db"


def main() -> None:
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    cur = con.cursor()
    print("=== BY SOURCE ===")
    rows = cur.execute(
        "SELECT source, COUNT(*) n, SUM(CASE WHEN score_ok=1 THEN 1 ELSE 0 END) ok "
        "FROM loads GROUP BY source ORDER BY n DESC"
    ).fetchall()
    for r in rows:
        print(f"  {r['source']:16} total={r['n']:5} score_ok={r['ok']}")

    print("\n=== RECENT RUNS ===")
    for r in cur.execute(
        "SELECT source, ok, added, updated, error, started_at, finished_at "
        "FROM scrape_runs ORDER BY id DESC LIMIT 20"
    ):
        print(
            f"  {r['source']:16} ok={r['ok']} +{r['added']} ~{r['updated']} err={r['error']}"
        )

    print("\n=== GEO CORRIDOR (base=москва, near=150, far=1500) ===")
    web_sources = (
        "perevozka24",
        "cargocash",
        "vezetvsem",
        "roolz",
        "ingruz",
        "avtodispetcher",
        "papacargo",
        "monopoly",
    )
    q = (
        "SELECT source, from_city, to_city, title, score, score_ok FROM loads "
        f"WHERE source IN ({','.join('?'*len(web_sources))}) "
        "ORDER BY id DESC LIMIT 5000"
    )
    items = cur.execute(q, web_sources).fetchall()
    ok = bad = unknown = 0
    reasons = Counter()
    samples_ok = []
    samples_bad = []
    for it in items:
        passed, reason, tags = geo_filter(
            base="москва",
            from_city=it["from_city"],
            to_city=it["to_city"],
            radius_km=150,
            far_radius_km=1500,
            backhaul_only=False,
        )
        reasons[reason] += 1
        if passed and reason in {"ok", "geo_partial", "geo_unknown", "no_route"}:
            if reason == "ok":
                ok += 1
                if len(samples_ok) < 8:
                    samples_ok.append(
                        f"{it['source']}: {it['from_city']}→{it['to_city']} ({tags})"
                    )
            else:
                unknown += 1
        else:
            bad += 1
            if len(samples_bad) < 6:
                samples_bad.append(
                    f"{it['source']}: {it['from_city']}→{it['to_city']} [{reason}]"
                )
    print(f"  sampled web loads: {len(items)}")
    print(f"  corridor ok: {ok}  soft/unknown: {unknown}  rejected: {bad}")
    print("  reasons:", dict(reasons))
    print("  ok samples:")
    for s in samples_ok:
        print("   ", s)
    print("  rejected samples:")
    for s in samples_bad:
        print("   ", s)

    print("\n=== NEW SOURCES CITY FILL ===")
    for src in ("cargocash", "vezetvsem", "roolz", "ingruz", "avtodispetcher"):
        n = cur.execute("SELECT COUNT(*) FROM loads WHERE source=?", (src,)).fetchone()[0]
        with_route = cur.execute(
            "SELECT COUNT(*) FROM loads WHERE source=? AND from_city IS NOT NULL AND to_city IS NOT NULL",
            (src,),
        ).fetchone()[0]
        print(f"  {src:16} n={n} with_route={with_route}")

    con.close()


if __name__ == "__main__":
    # ensure freight_core import path
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    main()
