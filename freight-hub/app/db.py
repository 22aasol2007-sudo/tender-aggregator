from __future__ import annotations

import hashlib
import json
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
        now = time.time()
        cur = await self.db.execute(
            "SELECT id, body, score FROM loads WHERE source=? AND external_id=?",
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
            await self.db.execute(
                """
                UPDATE loads SET
                    title=?, body=?, from_city=?, to_city=?, tonnage=?, volume_m3=?,
                    body_type=?, temps=?, price=?, load_date=?, phones=?, contacts=?,
                    url=?, score=?, score_ok=?, kind=?, fingerprint=?, route_fp=?,
                    km_from=?, km_to=?, route_km=?, price_per_km=?, raw_json=?, scraped_at=?
                WHERE id=?
                """,
                (*vals, row["id"]),
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
                now,
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
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        from app import config as _cfg

        sql = ["SELECT * FROM loads WHERE score >= ?"]
        args: list[Any] = [min_score]
        age = max_age_sec if max_age_sec is not None else float(_cfg.MAX_LOAD_AGE_SEC)
        if age > 0:
            sql.append("AND scraped_at >= ?")
            args.append(time.time() - age)
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
        if source:
            sql.append("AND source = ?")
            args.append(source)
        if body_type:
            sql.append("AND body_type = ?")
            args.append(body_type)
        if from_city:
            from app.parse import city_search_terms

            terms = city_search_terms(from_city) or [from_city.lower()]
            sql.append(
                "AND (" + " OR ".join(["LOWER(COALESCE(from_city,'')) LIKE ?"] * len(terms)) + ")"
            )
            args.extend([f"%{t}%" for t in terms])
        if to_city:
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
        else:
            sql.append("ORDER BY scraped_at DESC, score DESC LIMIT ? OFFSET ?")
        args.extend([limit, offset])
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
            out.append(d)
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
        # Weak / failed geo
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
        # Hard max age for everything
        await self.db.execute(
            "DELETE FROM loads WHERE scraped_at < ?",
            (now - strong,),
        )
        await self.db.commit()


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
