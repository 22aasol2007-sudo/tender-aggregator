from __future__ import annotations

import hashlib
import json
import statistics
import time
from pathlib import Path
from typing import Any

import aiosqlite


class HubDB:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._db: aiosqlite.Connection | None = None
        self._defer_commit = False

    async def connect(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._db = await aiosqlite.connect(self.path)
        self._db.row_factory = aiosqlite.Row
        await self._db.execute("PRAGMA journal_mode=WAL")
        await self._db.execute("PRAGMA synchronous=NORMAL")
        await self._db.execute("PRAGMA temp_store=MEMORY")
        await self._db.executescript(
            """
            CREATE TABLE IF NOT EXISTS loads (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source TEXT NOT NULL,
                external_id TEXT NOT NULL,
                title TEXT,
                body TEXT NOT NULL,
                from_city TEXT,
                to_city TEXT,
                tonnage REAL,
                volume_m3 REAL,
                body_type TEXT,
                temps TEXT,
                price TEXT,
                url TEXT,
                score INTEGER NOT NULL DEFAULT 0,
                kind TEXT,
                fingerprint TEXT NOT NULL,
                raw_json TEXT,
                created_at REAL NOT NULL,
                scraped_at REAL NOT NULL,
                UNIQUE(source, external_id)
            );
            CREATE INDEX IF NOT EXISTS idx_loads_scraped ON loads(scraped_at DESC);
            CREATE INDEX IF NOT EXISTS idx_loads_score ON loads(score DESC);
            CREATE INDEX IF NOT EXISTS idx_loads_fp ON loads(fingerprint);
            CREATE INDEX IF NOT EXISTS idx_loads_route ON loads(from_city, to_city);
            CREATE INDEX IF NOT EXISTS idx_loads_score_time ON loads(score DESC, scraped_at DESC);
            CREATE TABLE IF NOT EXISTS scrape_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source TEXT NOT NULL,
                ok INTEGER NOT NULL,
                added INTEGER NOT NULL DEFAULT 0,
                updated INTEGER NOT NULL DEFAULT 0,
                error TEXT,
                started_at REAL NOT NULL,
                finished_at REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS tg_health (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
            """
        )
        await self._migrate_columns()
        await self._db.commit()

    async def _migrate_columns(self) -> None:
        cur = await self.db.execute("PRAGMA table_info(loads)")
        cols = {r[1] for r in await cur.fetchall()}
        alters = []
        if "phones" not in cols:
            alters.append("ALTER TABLE loads ADD COLUMN phones TEXT")
        if "contacts" not in cols:
            alters.append("ALTER TABLE loads ADD COLUMN contacts TEXT")
        if "load_date" not in cols:
            alters.append("ALTER TABLE loads ADD COLUMN load_date TEXT")
        if "score_ok" not in cols:
            alters.append("ALTER TABLE loads ADD COLUMN score_ok INTEGER NOT NULL DEFAULT 1")
        if "route_fp" not in cols:
            alters.append("ALTER TABLE loads ADD COLUMN route_fp TEXT")
        if "km_from" not in cols:
            alters.append("ALTER TABLE loads ADD COLUMN km_from REAL")
        if "km_to" not in cols:
            alters.append("ALTER TABLE loads ADD COLUMN km_to REAL")
        if "route_km" not in cols:
            alters.append("ALTER TABLE loads ADD COLUMN route_km REAL")
        if "price_per_km" not in cols:
            alters.append("ALTER TABLE loads ADD COLUMN price_per_km REAL")
        for sql in alters:
            await self.db.execute(sql)
        await self.db.execute(
            "CREATE INDEX IF NOT EXISTS idx_loads_route_fp ON loads(route_fp, scraped_at DESC)"
        )

    async def close(self) -> None:
        if self._db:
            await self._db.close()
            self._db = None

    @property
    def db(self) -> aiosqlite.Connection:
        assert self._db is not None
        return self._db

    def begin_batch(self) -> None:
        self._defer_commit = True

    async def end_batch(self) -> None:
        self._defer_commit = False
        await self.db.commit()

    async def _commit(self) -> None:
        if not self._defer_commit:
            await self.db.commit()

    async def get_setting(self, key: str, default: str | None = None) -> str | None:
        cur = await self.db.execute("SELECT value FROM settings WHERE key=?", (key,))
        row = await cur.fetchone()
        return row["value"] if row else default

    async def set_setting(self, key: str, value: str) -> None:
        await self.db.execute(
            "INSERT INTO settings(key, value) VALUES(?,?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, value),
        )
        await self.db.commit()

    async def get_json_setting(self, key: str, default: Any) -> Any:
        raw = await self.get_setting(key)
        if not raw:
            return default
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return default

    async def set_json_setting(self, key: str, value: Any) -> None:
        await self.set_setting(key, json.dumps(value, ensure_ascii=False))

    async def set_tg_health(self, data: dict[str, Any]) -> None:
        await self.db.execute(
            "INSERT INTO tg_health(key, value) VALUES('status', ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (json.dumps(data, ensure_ascii=False),),
        )
        await self._commit()

    async def get_tg_health(self) -> dict[str, Any]:
        cur = await self.db.execute("SELECT value FROM tg_health WHERE key='status'")
        row = await cur.fetchone()
        if not row:
            return {}
        try:
            return json.loads(row["value"])
        except json.JSONDecodeError:
            return {}

    async def find_route_dup(
        self,
        route_fp: str,
        *,
        exclude_source: str,
        exclude_external_id: str,
        within_sec: float,
    ) -> dict[str, Any] | None:
        if not route_fp:
            return None
        cur = await self.db.execute(
            """
            SELECT id, source, external_id, score, scraped_at FROM loads
            WHERE route_fp = ?
              AND NOT (source = ? AND external_id = ?)
              AND scraped_at >= ?
            ORDER BY score DESC, scraped_at DESC
            LIMIT 1
            """,
            (route_fp, exclude_source, exclude_external_id, time.time() - within_sec),
        )
        row = await cur.fetchone()
        return dict(row) if row else None

    async def upsert_load(self, item: dict[str, Any]) -> str:
        """Insert or update. Returns 'added'|'updated'|'skipped'."""
        from app import config as _cfg

        now = time.time()
        max_age = float(_cfg.MAX_LOAD_AGE_SEC)
        created = item.get("created_at")
        try:
            created_f = float(created) if created is not None else None
        except (TypeError, ValueError):
            created_f = None
        if created_f is not None and created_f > 1e12:
            created_f /= 1000.0
        if created_f is None:
            created_f = now
        elif created_f > now + 2 * 3600:
            # Clock skew / bad parse → scrape time
            created_f = now
        elif created_f < now - max_age:
            # Explicit ancient publish time — do not revive as "now"
            return "skipped"
        cur = await self.db.execute(
            "SELECT id, body, score, created_at FROM loads WHERE source=? AND external_id=?",
            (item["source"], item["external_id"]),
        )
        row = await cur.fetchone()
        temps = item.get("temps")
        if isinstance(temps, list):
            temps = json.dumps(temps, ensure_ascii=False)
        phones = item.get("phones")
        if isinstance(phones, list):
            phones = json.dumps(phones, ensure_ascii=False)
        contacts = item.get("contacts")
        if isinstance(contacts, list):
            contacts = json.dumps(contacts, ensure_ascii=False)
        raw = item.get("raw_json")
        if isinstance(raw, (dict, list)):
            raw = json.dumps(raw, ensure_ascii=False)
        vals = (
            item.get("title"),
            item["body"],
            item.get("from_city"),
            item.get("to_city"),
            item.get("tonnage"),
            item.get("volume_m3"),
            item.get("body_type"),
            temps,
            item.get("price"),
            item.get("load_date"),
            phones,
            contacts,
            item.get("url"),
            int(item.get("score") or 0),
            int(item.get("score_ok") if item.get("score_ok") is not None else 1),
            item.get("kind"),
            item["fingerprint"],
            item.get("route_fp"),
            item.get("km_from"),
            item.get("km_to"),
            item.get("route_km"),
            item.get("price_per_km"),
            raw,
            now,
        )
        if row:
            # Keep created_at unless we now know a better (earlier) publish time within retention.
            prev_c = float(row["created_at"]) if row["created_at"] is not None else now
            new_created = prev_c
            if item.get("created_at") is not None:
                try:
                    cand = float(item["created_at"])
                    if cand > 1e12:
                        cand /= 1000.0
                    if (now - max_age) <= cand <= now + 2 * 3600 and cand < prev_c - 60:
                        new_created = cand
                except (TypeError, ValueError):
                    pass
            await self.db.execute(
                """
                UPDATE loads SET
                    title=?, body=?, from_city=?, to_city=?, tonnage=?, volume_m3=?,
                    body_type=?, temps=?, price=?, load_date=?, phones=?, contacts=?,
                    url=?, score=?, score_ok=?, kind=?, fingerprint=?, route_fp=?,
                    km_from=?, km_to=?, route_km=?, price_per_km=?, raw_json=?, scraped_at=?,
                    created_at=?
                WHERE id=?
                """,
                (*vals, new_created, row["id"]),
            )
            await self._commit()
            return "updated"
        await self.db.execute(
            """
            INSERT INTO loads (
                source, external_id, title, body, from_city, to_city, tonnage,
                volume_m3, body_type, temps, price, load_date, phones, contacts,
                url, score, score_ok, kind, fingerprint, route_fp, km_from, km_to,
                route_km, price_per_km, raw_json, created_at, scraped_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                item["source"],
                item["external_id"],
                *vals[:-1],
                created_f,
                now,
            ),
        )
        await self._commit()
        return "added"

    async def list_loads(
        self,
        *,
        q: str | None = None,
        source: str | None = None,
        sources: list[str] | None = None,
        body_type: str | None = None,
        from_city: str | None = None,
        to_city: str | None = None,
        min_score: int = 0,
        only_reefer: bool = False,
        shipper_only: bool = False,
        hide_drivers: bool = True,
        muted_directions: list[str] | None = None,
        sort: str = "time",
        hot_only: bool = False,
        hot_max_age_sec: float = 1800,
        geo_corridor: bool = True,
        near_km: float = 150,
        far_km: float = 1500,
        max_age_sec: float | None = None,
        tonnage_min: float | None = None,
        tonnage_max: float | None = None,
        volume_min: float | None = None,
        volume_max: float | None = None,
        ppk_min: float | None = None,
        price_min: float | None = None,
        route_km_min: float | None = None,
        route_km_max: float | None = None,
        freshness_hours: float | None = None,
        load_date_mode: str | None = None,
        loading: str | None = None,
        cargo_mode: str | None = None,
        payment: str | None = None,
        exact_from: bool = False,
        exact_to: bool = False,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        from app import config as _cfg
        from app.filters_ati import append_ati_filters
        from app.ingest import parse_price_rub

        sql = ["SELECT * FROM loads WHERE score >= ?"]
        args: list[Any] = [min_score]
        age = max_age_sec if max_age_sec is not None else float(_cfg.MAX_LOAD_AGE_SEC)
        if age > 0:
            # Age from publish/first-seen — never show > retention window
            cutoff = time.time() - age
            sql.append("AND created_at >= ? AND created_at <= ?")
            args.append(cutoff)
            args.append(time.time() + 2 * 3600)
        if geo_corridor:
            # One end ≤ near_km of Moscow, both ends ≤ far_km
            sql.append(
                "AND km_from IS NOT NULL AND km_to IS NOT NULL "
                "AND MIN(km_from, km_to) <= ? AND MAX(km_from, km_to) <= ?"
            )
            args.extend([near_km, far_km])
        if hot_only:
            sql.append("AND scraped_at >= ? AND score_ok = 1 AND score >= 70")
            args.append(time.time() - hot_max_age_sec)
        if sources:
            placeholders = ",".join("?" for _ in sources)
            sql.append(f"AND source IN ({placeholders})")
            args.extend(list(sources))
        elif source:
            sql.append("AND source = ?")
            args.append(source)
        if body_type:
            sql.append("AND body_type = ?")
            args.append(body_type)
        if from_city and not exact_from:
            from app.parse import city_search_terms

            terms = city_search_terms(from_city) or [from_city.lower()]
            sql.append(
                "AND (" + " OR ".join(["LOWER(COALESCE(from_city,'')) LIKE ?"] * len(terms)) + ")"
            )
            args.extend([f"%{t}%" for t in terms])
        if to_city and not exact_to:
            from app.parse import city_search_terms

            terms = city_search_terms(to_city) or [to_city.lower()]
            sql.append(
                "AND (" + " OR ".join(["LOWER(COALESCE(to_city,'')) LIKE ?"] * len(terms)) + ")"
            )
            args.extend([f"%{t}%" for t in terms])
        if only_reefer:
            sql.append(
                "AND (body_type IN ('reefer','isotherm') OR temps LIKE '%реф%' "
                "OR temps LIKE '%+%' OR LOWER(body) LIKE '%реф%' OR LOWER(body) LIKE '%изотерм%')"
            )
        if shipper_only:
            # "other" = cargo-like posts without strong keywords (common in TG/MAX)
            sql.append("AND kind IN ('shipper','mixed','other')")
        elif hide_drivers:
            sql.append("AND IFNULL(kind,'') != 'driver'")
        if muted_directions:
            for d in muted_directions:
                d = (d or "").lower().strip()
                if not d:
                    continue
                sql.append(
                    "AND LOWER(COALESCE(from_city,'')) NOT LIKE ? "
                    "AND LOWER(COALESCE(to_city,'')) NOT LIKE ? "
                    "AND LOWER(COALESCE(body,'')) NOT LIKE ?"
                )
                like = f"%{d}%"
                args.extend([like, like, like])
        append_ati_filters(
            sql,
            args,
            tonnage_min=tonnage_min,
            tonnage_max=tonnage_max,
            volume_min=volume_min,
            volume_max=volume_max,
            ppk_min=ppk_min,
            price_min=None,  # applied after fetch (price is free text)
            route_km_min=route_km_min,
            route_km_max=route_km_max,
            freshness_hours=freshness_hours,
            load_date_mode=load_date_mode,
            loading=loading,
            cargo_mode=cargo_mode,
            payment=payment,
            exact_from=exact_from,
            exact_to=exact_to,
            from_city=from_city,
            to_city=to_city,
            hard_tonnage_min=float(_cfg.TONNAGE_MIN),
            hard_tonnage_max=float(_cfg.TONNAGE_MAX),
        )
        if q:
            like = f"%{q.lower()}%"
            sql.append(
                "AND (LOWER(COALESCE(body,'')) LIKE ? OR LOWER(COALESCE(title,'')) LIKE ? "
                "OR LOWER(COALESCE(from_city,'')) LIKE ? OR LOWER(COALESCE(to_city,'')) LIKE ? "
                "OR LOWER(COALESCE(phones,'')) LIKE ? OR LOWER(COALESCE(contacts,'')) LIKE ?)"
            )
            args.extend([like, like, like, like, like, like])
        if sort == "score":
            sql.append("ORDER BY score DESC, scraped_at DESC LIMIT ? OFFSET ?")
        elif sort == "ppk":
            # Higher ₽/km first (carrier wants more pay per km); unknowns last
            sql.append(
                "ORDER BY (price_per_km IS NULL) ASC, price_per_km DESC, "
                "score DESC, scraped_at DESC LIMIT ? OFFSET ?"
            )
        elif sort == "near":
            sql.append(
                "ORDER BY (CASE WHEN km_from IS NULL AND km_to IS NULL THEN 1 ELSE 0 END) ASC, "
                "MIN(COALESCE(km_from, 1e9), COALESCE(km_to, 1e9)) ASC, "
                "score DESC, scraped_at DESC LIMIT ? OFFSET ?"
            )
        elif sort == "route":
            sql.append(
                "ORDER BY (route_km IS NULL) ASC, route_km ASC, scraped_at DESC LIMIT ? OFFSET ?"
            )
        elif sort in {"time", "date", "posted"}:
            # First-seen time (= when we consider the ad posted into our feed)
            sql.append("ORDER BY created_at DESC, score DESC LIMIT ? OFFSET ?")
        else:
            sql.append("ORDER BY created_at DESC, score DESC LIMIT ? OFFSET ?")
        # Fetch extra when price_min post-filter may drop rows
        fetch_limit = limit
        fetch_offset = offset
        if price_min is not None and float(price_min) > 0:
            fetch_limit = min(500, max(limit * 3, limit + 50))
            fetch_offset = 0
        args.extend([fetch_limit, fetch_offset])
        cur = await self.db.execute(" ".join(sql), args)
        rows = await cur.fetchall()
        out = []
        for r in rows:
            d = dict(r)
            for key in ("phones", "contacts", "temps"):
                val = d.get(key)
                if isinstance(val, str) and val.startswith("["):
                    try:
                        d[key] = json.loads(val)
                    except json.JSONDecodeError:
                        pass
            if price_min is not None and float(price_min) > 0:
                amount = parse_price_rub(d.get("price"))
                if amount is None or amount < float(price_min):
                    continue
            out.append(d)
        if price_min is not None and float(price_min) > 0:
            out = out[offset : offset + limit]
        return out

    async def loads_since(self, since_id: int, limit: int = 100) -> list[dict[str, Any]]:
        cur = await self.db.execute(
            "SELECT * FROM loads WHERE id > ? ORDER BY id ASC LIMIT ?",
            (since_id, limit),
        )
        return [dict(r) for r in await cur.fetchall()]

    async def stats(self) -> dict[str, Any]:
        cur = await self.db.execute("SELECT COUNT(*) AS c FROM loads")
        total = (await cur.fetchone())["c"]
        cur = await self.db.execute(
            "SELECT source, COUNT(*) AS c FROM loads GROUP BY source ORDER BY c DESC"
        )
        by_source = {r["source"]: r["c"] for r in await cur.fetchall()}
        cur = await self.db.execute(
            "SELECT * FROM scrape_runs ORDER BY id DESC LIMIT 20"
        )
        runs = [dict(r) for r in await cur.fetchall()]
        return {"total": total, "by_source": by_source, "recent_runs": runs}

    async def latest_scrape_ok(self) -> dict[str, bool]:
        """Latest scrape_runs.ok per source (True/False). Missing sources omitted."""
        cur = await self.db.execute(
            """
            SELECT source, ok FROM scrape_runs
            WHERE id IN (SELECT MAX(id) FROM scrape_runs GROUP BY source)
            """
        )
        return {str(r["source"]): bool(r["ok"]) for r in await cur.fetchall()}

    async def backfill_route_km(self, limit: int = 2000) -> int:
        """Fill missing route_km from from_city/to_city. Returns updated row count."""
        from app.ingest import calc_price_per_km

        cur = await self.db.execute(
            """
            SELECT id, from_city, to_city, price, price_per_km FROM loads
            WHERE route_km IS NULL
              AND from_city IS NOT NULL AND TRIM(from_city) != ''
              AND to_city IS NOT NULL AND TRIM(to_city) != ''
            ORDER BY id DESC
            LIMIT ?
            """,
            (limit,),
        )
        rows = await cur.fetchall()
        updated = 0
        for r in rows:
            route_km, ppk = calc_price_per_km(r["price"], r["from_city"], r["to_city"])
            if route_km is None:
                continue
            if r["price_per_km"] is None and ppk is not None:
                await self.db.execute(
                    "UPDATE loads SET route_km=?, price_per_km=? WHERE id=?",
                    (route_km, ppk, r["id"]),
                )
            else:
                await self.db.execute(
                    "UPDATE loads SET route_km=? WHERE id=?",
                    (route_km, r["id"]),
                )
            updated += 1
        if updated:
            await self.db.commit()
        return updated

    async def log_run(
        self, source: str, ok: bool, added: int, updated: int, error: str | None, started: float
    ) -> None:
        await self.db.execute(
            """
            INSERT INTO scrape_runs (source, ok, added, updated, error, started_at, finished_at)
            VALUES (?,?,?,?,?,?,?)
            """,
            (source, 1 if ok else 0, added, updated, error, started, time.time()),
        )
        await self.db.commit()

    async def cleanup(self, older_than_sec: float | None = None) -> None:
        from app import config as _cfg

        sec = float(older_than_sec if older_than_sec is not None else _cfg.MAX_LOAD_AGE_SEC)
        await self.cleanup_smart(strong_sec=sec)

    async def cleanup_smart(
        self,
        *,
        strong_sec: float | None = None,
        weak_sec: float | None = None,
        junk_sec: float | None = None,
    ) -> None:
        from app import config as _cfg

        strong = float(strong_sec if strong_sec is not None else _cfg.MAX_LOAD_AGE_SEC)
        weak = float(weak_sec if weak_sec is not None else min(3 * 86400, strong))
        junk = float(junk_sec if junk_sec is not None else min(2 * 86400, strong))
        now = time.time()
        # Weak / failed geo — drop if not refreshed recently
        await self.db.execute(
            "DELETE FROM loads WHERE scraped_at < ? AND (score < 40 OR IFNULL(score_ok,1)=0)",
            (now - weak,),
        )
        # Same-city junk
        await self.db.execute(
            """
            DELETE FROM loads WHERE scraped_at < ?
              AND from_city IS NOT NULL AND to_city IS NOT NULL
              AND LOWER(from_city)=LOWER(to_city)
            """,
            (now - junk,),
        )
        # Hard max age from publish/first-seen (created_at)
        await self.db.execute(
            "DELETE FROM loads WHERE created_at < ?",
            (now - strong,),
        )
        # Drop absurd future stamps
        await self.db.execute(
            "DELETE FROM loads WHERE created_at > ?",
            (now + 2 * 86400,),
        )
        # Also drop ads not seen on boards for the full retention window
        await self.db.execute(
            "DELETE FROM loads WHERE scraped_at < ?",
            (now - strong,),
        )
        # Out-of-band declared tonnage
        await self.db.execute(
            "DELETE FROM loads WHERE tonnage IS NOT NULL AND (tonnage < ? OR tonnage > ?)",
            (float(_cfg.TONNAGE_MIN), float(_cfg.TONNAGE_MAX)),
        )
        await self.db.commit()

    async def vacuum_if_due(self) -> bool:
        """Run SQLite VACUUM at most every VACUUM_EVERY_HOURS."""
        from app import config as _cfg

        every = float(getattr(_cfg, "VACUUM_EVERY_HOURS", 12) or 0)
        if every <= 0:
            return False
        raw = await self.get_setting("last_vacuum_at")
        try:
            last = float(raw) if raw else 0.0
        except (TypeError, ValueError):
            last = 0.0
        now = time.time()
        if now - last < every * 3600:
            return False
        try:
            await self.db.execute("VACUUM")
            await self.db.commit()
            await self.set_setting("last_vacuum_at", str(now))
            return True
        except Exception:
            return False

    async def find_route_siblings(
        self,
        route_fp: str,
        *,
        within_sec: float,
        limit: int = 8,
    ) -> list[dict[str, Any]]:
        if not route_fp:
            return []
        cur = await self.db.execute(
            """
            SELECT id, source, external_id, url, score, scraped_at FROM loads
            WHERE route_fp = ? AND scraped_at >= ?
            ORDER BY score DESC, scraped_at DESC
            LIMIT ?
            """,
            (route_fp, time.time() - within_sec, limit),
        )
        return [dict(r) for r in await cur.fetchall()]

    async def stats_sources_in_window(self, *, days: float = 7) -> list[dict[str, Any]]:
        cutoff = time.time() - float(days) * 86400
        cur = await self.db.execute(
            """
            SELECT source, COUNT(*) AS c FROM loads
            WHERE created_at >= ?
            GROUP BY source ORDER BY c DESC
            """,
            (cutoff,),
        )
        return [{"source": r["source"], "count": int(r["c"])} for r in await cur.fetchall()]

    async def route_stats(
        self,
        *,
        from_city: str,
        to_city: str,
        days: float = 7,
    ) -> dict[str, Any]:
        from app.ingest import parse_price_rub
        from app.parse import city_search_terms

        cutoff = time.time() - float(days) * 86400
        f_terms = city_search_terms(from_city) or [from_city.lower()]
        t_terms = city_search_terms(to_city) or [to_city.lower()]
        f_sql = " OR ".join(["LOWER(COALESCE(from_city,'')) LIKE ?"] * len(f_terms))
        t_sql = " OR ".join(["LOWER(COALESCE(to_city,'')) LIKE ?"] * len(t_terms))
        args: list[Any] = [cutoff, *[f"%{x}%" for x in f_terms], *[f"%{x}%" for x in t_terms]]
        cur = await self.db.execute(
            f"""
            SELECT price, price_per_km, route_km FROM loads
            WHERE created_at >= ?
              AND ({f_sql})
              AND ({t_sql})
            """,
            args,
        )
        rows = await cur.fetchall()
        ppks: list[float] = []
        prices: list[float] = []
        kms: list[float] = []
        for r in rows:
            if r["price_per_km"] is not None:
                try:
                    ppks.append(float(r["price_per_km"]))
                except (TypeError, ValueError):
                    pass
            amt = parse_price_rub(r["price"])
            if amt is not None:
                prices.append(float(amt))
            if r["route_km"] is not None:
                try:
                    kv = float(r["route_km"])
                    if kv > 0:
                        kms.append(kv)
                except (TypeError, ValueError):
                    pass
        med_ppk = float(statistics.median(ppks)) if ppks else None
        med_price = float(statistics.median(prices)) if prices else None
        med_km = float(statistics.median(kms)) if kms else None

        def _pct(vals: list[float], p: float) -> float | None:
            if not vals:
                return None
            if len(vals) == 1:
                return float(vals[0])
            s = sorted(vals)
            if len(s) < 4:
                return float(s[0] if p <= 25 else s[-1] if p >= 75 else statistics.median(s))
            try:
                qs = statistics.quantiles(s, n=4, method="inclusive")
                return float(qs[0] if p <= 25 else qs[2])
            except Exception:
                return float(statistics.median(s))

        return {
            "count": len(rows),
            "n_priced": len(prices),
            "n_ppk": len(ppks),
            "median_ppk": round(med_ppk, 1) if med_ppk is not None else None,
            "median_price": round(med_price, 0) if med_price is not None else None,
            "median_km": round(med_km, 1) if med_km is not None else None,
            "p25_price": round(_pct(prices, 25), 0) if prices else None,
            "p75_price": round(_pct(prices, 75), 0) if prices else None,
            "p25_ppk": round(_pct(ppks, 25), 1) if ppks else None,
            "p75_ppk": round(_pct(ppks, 75), 1) if ppks else None,
        }

    async def count_outside_corridor(
        self,
        *,
        sources: list[str] | None = None,
        source: str | None = None,
        near_km: float = 150,
        far_km: float = 1500,
        min_score: int = 0,
        max_age_sec: float | None = None,
    ) -> int:
        """How many loads exist for channel but fail the geo corridor filter."""
        from app import config as _cfg

        age = max_age_sec if max_age_sec is not None else float(_cfg.MAX_LOAD_AGE_SEC)
        sql = [
            "SELECT COUNT(*) AS c FROM loads WHERE score >= ?",
            "AND created_at >= ? AND created_at <= ?",
            "AND NOT ("
            "km_from IS NOT NULL AND km_to IS NOT NULL "
            "AND MIN(km_from, km_to) <= ? AND MAX(km_from, km_to) <= ?"
            ")",
        ]
        args: list[Any] = [
            min_score,
            time.time() - age,
            time.time() + 2 * 3600,
            near_km,
            far_km,
        ]
        if sources:
            placeholders = ",".join("?" for _ in sources)
            sql.append(f"AND source IN ({placeholders})")
            args.extend(list(sources))
        elif source:
            sql.append("AND source = ?")
            args.append(source)
        cur = await self.db.execute(" ".join(sql), args)
        row = await cur.fetchone()
        return int(row["c"] if row else 0)

    async def backhaul_to_base_stats(
        self,
        *,
        origin: str,
        base: str,
        days: float = 7,
    ) -> dict[str, Any]:
        """Loads from origin-area toward base (to_city near base)."""
        return await self.route_stats(from_city=origin, to_city=base, days=days)

    async def backhaul_city_ranking(
        self,
        *,
        base: str = "москва",
        days: float = 7,
        limit: int = 25,
    ) -> list[dict[str, Any]]:
        """Rank origin cities by count of loads toward base (backhaul liquidity)."""
        from app.parse import city_search_terms

        cutoff = time.time() - float(days) * 86400
        b_terms = city_search_terms(base) or [base.lower()]
        t_sql = " OR ".join(["LOWER(COALESCE(to_city,'')) LIKE ?"] * len(b_terms))
        args: list[Any] = [cutoff, *[f"%{x}%" for x in b_terms]]
        cur = await self.db.execute(
            f"""
            SELECT LOWER(TRIM(from_city)) AS city, COUNT(*) AS c,
                   AVG(price_per_km) AS avg_ppk
            FROM loads
            WHERE created_at >= ?
              AND from_city IS NOT NULL AND TRIM(from_city) != ''
              AND ({t_sql})
            GROUP BY LOWER(TRIM(from_city))
            HAVING c >= 1
            ORDER BY c DESC
            LIMIT ?
            """,
            [*args, int(limit)],
        )
        out = []
        for r in await cur.fetchall():
            out.append(
                {
                    "city": r["city"],
                    "backhaul_n": int(r["c"]),
                    "avg_ppk": round(float(r["avg_ppk"]), 1) if r["avg_ppk"] is not None else None,
                }
            )
        return out

    async def backhaul_nearby_to_base(
        self,
        *,
        origin: str,
        base: str = "москва",
        radius_km: float = 100,
        days: float = 7,
        limit: int = 20,
    ) -> dict[str, Any]:
        """Backhaul loads to base from origin city and cities within radius_km."""
        from freight_core.geo import distance_km

        ranking = await self.backhaul_city_ranking(base=base, days=days, limit=200)
        origin_n = (origin or "").strip().lower().replace("ё", "е")
        nearby: list[dict[str, Any]] = []
        total = 0
        exact = 0
        for row in ranking:
            city = str(row.get("city") or "").strip().lower()
            if not city:
                continue
            n = int(row.get("backhaul_n") or 0)
            if city == origin_n or origin_n in city or city in origin_n:
                dist = 0.0
            else:
                dist = distance_km(origin_n, city)
                if dist is None or dist > float(radius_km):
                    continue
            item = {
                "city": city,
                "backhaul_n": n,
                "avg_ppk": row.get("avg_ppk"),
                "km_from_origin": round(float(dist), 1),
            }
            nearby.append(item)
            total += n
            if dist == 0.0:
                exact += n
        nearby.sort(key=lambda x: (-int(x["backhaul_n"]), float(x["km_from_origin"])))
        return {
            "origin": origin_n,
            "base": (base or "").strip().lower(),
            "radius_km": float(radius_km),
            "count": total,
            "count_exact": exact,
            "count_radius": total - exact,
            "cities": nearby[: int(limit)],
        }


def make_fingerprint(*parts: str) -> str:
    blob = "|".join((p or "").lower().strip() for p in parts)
    return hashlib.sha1(blob.encode("utf-8")).hexdigest()


def make_route_fingerprint(
    from_city: str | None,
    to_city: str | None,
    tonnage: float | None,
    load_date: str | None = None,
) -> str:
    day = (load_date or time.strftime("%Y-%m-%d")).strip().lower()
    t = "" if tonnage is None else f"{float(tonnage):g}"
    return make_fingerprint(from_city or "", to_city or "", t, day)
