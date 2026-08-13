from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

import app._bootstrap  # noqa: F401
from app import config
from app.auth import require_write_token
from app.db import HubDB
from app.scrapers.max_src import MaxIngest
from app.scrapers.telegram_src import TelegramIngest
from app.worker import ScrapeWorker

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)
log = logging.getLogger("hub")

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "web"

db = HubDB(config.DB_PATH)
worker = ScrapeWorker(db)
tg: TelegramIngest | None = None
mx: MaxIngest | None = None


@asynccontextmanager
async def lifespan(_: FastAPI):
    global tg, mx
    await db.connect()
    # Defaults: one leg ≤150 km of Moscow, other ≤1500 km (either direction)
    default_profile = '{"base":"москва","radius":150,"radius_far":1500}'
    raw_prof = await db.get_setting("truck_profile")
    if raw_prof in (None, "{}", ""):
        await db.set_setting("truck_profile", default_profile)
    else:
        try:
            import json as _json

            prof = _json.loads(raw_prof) if isinstance(raw_prof, str) else (raw_prof or {})
            if isinstance(prof, dict):
                changed = False
                if not prof.get("base"):
                    prof["base"] = "москва"
                    changed = True
                if prof.get("radius") in (None, ""):
                    prof["radius"] = 150
                    changed = True
                if prof.get("radius_far") in (None, "") and prof.get("far_radius") in (None, ""):
                    prof["radius_far"] = 1500
                    changed = True
                if changed:
                    await db.set_setting("truck_profile", _json.dumps(prof, ensure_ascii=False))
        except Exception:
            pass
    if await db.get_setting("muted_directions") is None:
        await db.set_setting("muted_directions", "[]")
    # Clear legacy false-positive streaks (counted "0 added" even when boards returned duplicates)
    await db.set_setting("zero_add_streaks", "{}")
    # Purge week-old (and older) loads immediately — created_at based
    try:
        await db.cleanup_smart()
        log.info("startup cleanup done")
    except Exception as exc:
        log.warning("startup cleanup failed: %s", exc)
    try:
        n = await db.backfill_route_km()
        if n:
            log.info("backfilled route_km for %s loads", n)
    except Exception as exc:
        log.warning("route_km backfill failed: %s", exc)
    worker.start()

    # Listeners start independently — one failure must not block the other
    async def _boot_tg() -> None:
        global tg
        if not (config.ENABLE_TG and config.API_ID and config.API_HASH):
            await db.set_tg_health(
                {
                    "ok": False,
                    "note": "disabled_or_missing_creds",
                    "resolved": 0,
                    "watched": 0,
                    "hint": "Set API_ID/API_HASH, run login_tg.py, use VPN if t.me times out",
                }
            )
            return
        tg = TelegramIngest(db)
        try:
            await tg.start()
        except Exception as exc:
            log.warning("TG start failed: %s", exc)
            await db.set_tg_health(
                {"ok": False, "note": f"start_failed: {exc}", "updated_at": __import__("time").time()}
            )

    async def _boot_max() -> None:
        global mx
        if not config.ENABLE_MAX:
            await db.set_setting(
                "max_health",
                __import__("json").dumps({"ok": False, "note": "disabled"}, ensure_ascii=False),
            )
            return
        mx = MaxIngest(db)
        try:
            await mx.start()
        except Exception as exc:
            log.warning("MAX start failed: %s", exc)
            await db.set_setting(
                "max_health",
                __import__("json").dumps(
                    {"ok": False, "note": f"start_failed: {exc}", "updated_at": __import__("time").time()},
                    ensure_ascii=False,
                ),
            )

    async def _watchdog() -> None:
        import json as _json
        import time as _time

        while True:
            await asyncio.sleep(config.WATCHDOG_SEC)
            try:
                tg_h = await db.get_tg_health()
                mx_raw = await db.get_setting("max_health")
                try:
                    mx_h = _json.loads(mx_raw) if isinstance(mx_raw, str) and mx_raw else (mx_raw or {})
                except Exception:
                    mx_h = {}
                now = _time.time()
                if config.ENABLE_TG and config.API_ID and (not tg or not getattr(tg, "ok", False)):
                    age = now - float(tg_h.get("updated_at") or 0)
                    if age > config.WATCHDOG_SEC * 2:
                        log.warning("watchdog: TG stale/down — restarting")
                        if tg:
                            try:
                                await tg.stop()
                            except Exception:
                                pass
                        await _boot_tg()
                if config.ENABLE_MAX and (not mx or not getattr(mx, "ok", False)):
                    age = now - float((mx_h or {}).get("updated_at") or 0)
                    if age > config.WATCHDOG_SEC * 2:
                        log.warning("watchdog: MAX stale/down — restarting")
                        if mx:
                            try:
                                await mx.stop()
                            except Exception:
                                pass
                        await _boot_max()
            except Exception as exc:
                log.debug("watchdog: %s", exc)

    import asyncio

    asyncio.create_task(_boot_tg())
    asyncio.create_task(_boot_max())
    asyncio.create_task(_watchdog())
    yield
    await worker.stop()
    if tg:
        await tg.stop()
    if mx:
        await mx.stop()
    await db.close()


app = FastAPI(title="Freight Hub", version="0.3.0", lifespan=lifespan)

if config.CORS_ORIGINS:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=config.CORS_ORIGINS,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )


class ScrapeOut(BaseModel):
    results: list[dict[str, Any]]


class TruckProfile(BaseModel):
    base: str | None = None
    body: str | None = None
    tonnage: float | None = None
    volume: float | None = None
    radius: float | None = None
    radius_far: float | None = None
    backhaul: bool = False
    temp: str | None = None


class MuteIn(BaseModel):
    direction: str = Field(min_length=2, max_length=80)


class TgPasswordIn(BaseModel):
    password: str = Field(min_length=1, max_length=200)


@app.get("/api/health")
async def health() -> dict[str, Any]:
    import json as _json
    import time as _time

    st = await db.stats()
    tg_h = await db.get_tg_health()
    mx_raw = await db.get_setting("max_health")
    try:
        mx_h = _json.loads(mx_raw) if isinstance(mx_raw, str) and mx_raw else (mx_raw or {})
    except Exception:
        mx_h = {}
    if not isinstance(mx_h, dict):
        mx_h = {}
    now = _time.time()
    hints: list[str] = []
    tg_alive = bool(tg and getattr(tg, "ok", False))
    mx_alive = bool(mx and getattr(mx, "ok", False) and mx_h.get("ok"))

    def _status(ok: bool, note: str = "") -> str:
        if ok:
            return "on"
        n = (note or "").lower()
        if "reconnect" in n or "timeout" in n:
            return "warn"
        return "off"

    tg_status = _status(tg_alive, str((tg_h or {}).get("note") or ""))
    max_status = _status(mx_alive, str((mx_h or {}).get("note") or ""))
    web_sources = ("perevozka24", "cargocash", "vezetvsem", "papacargo", "avtodispetcher")
    web_count = sum(int((st.get("by_source") or {}).get(s) or 0) for s in web_sources)
    sites_status = "on" if web_count > 0 else "warn"

    tg_need_login = False
    if not tg_alive:
        if not config.API_ID or not config.API_HASH:
            hints.append("Нет API_ID/API_HASH — основной объём заявок идёт из Telegram.")
        else:
            note = str((tg_h or {}).get("note") or "")
            low = note.lower()
            if any(
                x in low
                for x in (
                    "need_qr_login",
                    "two different ip",
                    "session_revoked",
                    "authkey",
                    "unauthorized",
                    "revoked",
                    "start_failed",
                )
            ):
                tg_need_login = True
                hints.append("Telegram: сессия отозвана или недействительна. Войдите: /tg-login")
            else:
                tg_need_login = True
                hints.append("Telegram отключён. Проверьте сессию: /tg-login")
    elif tg_h.get("failed_count"):
        fails = tg_h.get("failed_resolve") or []
        if isinstance(fails, list) and fails:
            names = ", ".join(f"@{u}" for u in fails[:5])
            more = f" (+{len(fails)-5})" if len(fails) > 5 else ""
            hints.append(f"Telegram: не резолвится: {names}{more}")
        else:
            hints.append(f"Telegram: не резолвится чатов: {tg_h.get('failed_count')}")

    zero_raw = await db.get_setting("zero_add_streaks")
    try:
        zero_streaks = _json.loads(zero_raw) if zero_raw else {}
    except Exception:
        zero_streaks = {}
    drought: list[str] = []
    if isinstance(zero_streaks, dict):
        for src, n in zero_streaks.items():
            try:
                if int(n) >= config.ZERO_ADD_STREAK_WARN:
                    drought.append(f"{src}×{n}")
            except (TypeError, ValueError):
                pass
    if drought:
        hints.append(
            "Источники без ответа (пусто/ошибка несколько циклов): " + ", ".join(drought)
        )

    if config.ENABLE_MAX and not mx_alive:
        note = mx_h.get("note") or "off"
        if note in {"no_session", "disabled", "off"} or not mx_h:
            hints.append("MAX: нет сессии — войдите через login_max.py")
        else:
            hints.append(f"MAX: {note}")

    # Silent messenger channels
    for src, label, alive in (
        ("telegram", "Telegram", tg_alive),
        ("max", "MAX", mx_alive),
    ):
        if not alive:
            continue
        try:
            last = float((await db.get_setting(f"last_ingest_{src}")) or 0)
        except Exception:
            last = 0.0
        if last and now - last > 3 * 3600:
            hours = int((now - last) / 3600)
            hints.append(f"{label}: нет новых заявок уже {hours} ч")

    if st["total"] < 30:
        hints.append("Мало заявок в ленте — обновите источники.")

    latest_ts = 0.0
    for key in ("telegram", "max"):
        try:
            latest_ts = max(latest_ts, float((await db.get_setting(f"last_ingest_{key}")) or 0))
        except Exception:
            pass
    for src_key in ("updated_at",):
        try:
            latest_ts = max(latest_ts, float((tg_h or {}).get(src_key) or 0))
            latest_ts = max(latest_ts, float((mx_h or {}).get(src_key) or 0))
        except Exception:
            pass

    # Parse coverage: chats (TG + MAX) and site scrapers
    def _i(v: Any, default: int = 0) -> int:
        try:
            return int(v)
        except (TypeError, ValueError):
            return default

    tg_ok = _i((tg_h or {}).get("resolved")) if tg_alive else 0
    tg_total = _i((tg_h or {}).get("watched"))
    if tg_total <= 0 and config.ENABLE_TG:
        from app.defaults import DEFAULT_CHATS

        tg_total = min(len(DEFAULT_CHATS), config.MAX_TG_CHATS)
    tg_failed = _i((tg_h or {}).get("failed_count"))
    if tg_alive and tg_total < tg_ok + tg_failed:
        tg_total = tg_ok + tg_failed

    mx_ok = 0
    mx_total = 0
    if config.ENABLE_MAX:
        mx_ok = _i((mx_h or {}).get("resolved")) if mx_alive else 0
        mx_failed = _i((mx_h or {}).get("failed_count"))
        mx_watched = _i((mx_h or {}).get("watched"))
        mx_total = max(mx_watched + mx_failed, mx_ok + mx_failed)
        if mx_total <= 0 and mx:
            try:
                mx_total = len(getattr(mx, "_channels", []) or [])
            except Exception:
                pass

    chats_ok = tg_ok + mx_ok
    chats_total = tg_total + mx_total

    enabled_sites = [
        s.scraper.name
        for s in worker.slots
        if s.enabled and getattr(s.scraper, "name", None)
    ]
    latest_ok = await db.latest_scrape_ok()
    sites_ok = sum(1 for name in enabled_sites if latest_ok.get(name) is True)
    sites_total = len(enabled_sites)

    coverage = {
        "chats": {
            "ok": chats_ok,
            "total": chats_total,
            "tg_ok": tg_ok,
            "tg_total": tg_total,
            "max_ok": mx_ok,
            "max_total": mx_total,
        },
        "sites": {
            "ok": sites_ok,
            "total": sites_total,
            "sources": [
                {"name": name, "ok": bool(latest_ok.get(name))}
                for name in enabled_sites
            ],
        },
    }

    return {
        "ok": True,
        "tg": tg_alive,
        "tg_configured": bool(config.API_ID and config.API_HASH),
        "tg_health": tg_h,
        "max": mx_alive,
        "max_health": mx_h,
        "total_loads": st["total"],
        "by_source": st["by_source"],
        "statuses": {"tg": tg_status, "max": max_status, "sites": sites_status},
        "coverage": coverage,
        "updated_ago_sec": max(0, int(now - latest_ts)) if latest_ts else 0,
        "hints": hints,
        "tg_need_login": tg_need_login,
        "tg_down": not tg_alive,
        "zero_add_streaks": zero_streaks if isinstance(zero_streaks, dict) else {},
        "write_token_required": bool(config.HUB_WRITE_TOKEN),
        "public_url": "https://freight-edge.vercel.app",
        "optimizations": {
            "parallel_scrape": True,
            "per_source_intervals": True,
            "cross_dedup_hours": config.CROSS_DEDUP_HOURS,
            "wal": True,
            "watchdog_sec": config.WATCHDOG_SEC,
        },
    }


@app.get("/api/stats")
async def stats() -> dict[str, Any]:
    st = await db.stats()
    st["tg_health"] = await db.get_tg_health()
    return st


SOURCE_GROUPS: dict[str, list[str]] = {
    "telegram": ["telegram", "tg_public"],
    "max": ["max"],
    "sites": [
        "perevozka24",
        "cargocash",
        "vezetvsem",
        "papacargo",
        "avtodispetcher",
        "ati",
        "monopoly",
        "roolz",
        "ingruz",
    ],
}


@app.get("/api/loads")
async def loads(
    q: str | None = None,
    source: str | None = None,
    channel: str | None = Query(None, pattern="^(all|telegram|max|sites)$"),
    body: str | None = Query(None, alias="body_type"),
    frm: str | None = Query(None, alias="from"),
    to: str | None = None,
    min_score: int = Query(40, ge=0, le=100),
    reefer: bool = False,
    shipper_only: bool = True,
    hide_drivers: bool = True,
    hot: bool = False,
    geo: bool = True,
    sort: str = Query("date", pattern="^(time|date|posted|score|ppk|near|route)$"),
    tonnage_min: float | None = Query(None, ge=0, le=100),
    tonnage_max: float | None = Query(None, ge=0, le=100),
    volume_min: float | None = Query(None, ge=0, le=500),
    volume_max: float | None = Query(None, ge=0, le=500),
    ppk_min: float | None = Query(None, ge=0, le=1_000_000),
    price_min: float | None = Query(None, ge=0, le=50_000_000),
    route_km_min: float | None = Query(None, ge=0, le=20_000),
    route_km_max: float | None = Query(None, ge=0, le=20_000),
    freshness_hours: float | None = Query(None, ge=0, le=720),
    load_date_mode: str | None = Query(None, pattern="^(any|today|tomorrow|3d|week)?$"),
    loading: str | None = Query(None, pattern="^(any|rear|side|top)?$"),
    cargo_mode: str | None = Query(None, pattern="^(any|ftl|ltl)?$"),
    payment: str | None = Query(None, pattern="^(any|with_rate|cash|nds|no_nds|prepay)?$"),
    exact_from: bool = False,
    exact_to: bool = False,
    limit: int = Query(200, ge=1, le=500),
    offset: int = Query(0, ge=0),
) -> dict[str, Any]:
    muted = await db.get_json_setting("muted_directions", [])
    if not isinstance(muted, list):
        muted = []
    profile = await db.get_json_setting("truck_profile", {})
    if not isinstance(profile, dict):
        profile = {}
    base_city = str(profile.get("base") or "москва").strip().lower() or "москва"
    try:
        near = float(profile.get("radius") or 150)
    except (TypeError, ValueError):
        near = 150.0
    try:
        far = float(profile.get("radius_far") or profile.get("far_radius") or 1500)
    except (TypeError, ValueError):
        far = 1500.0
    channel_key = (channel or "all").strip().lower() or "all"
    group_sources = SOURCE_GROUPS.get(channel_key)

    def _none_if_any(val: str | None) -> str | None:
        v = (val or "").strip().lower()
        return None if v in {"", "any", "all"} else v

    rows = await db.list_loads(
        q=q,
        source=source if not group_sources else None,
        sources=group_sources,
        body_type=body,
        from_city=frm,
        to_city=to,
        min_score=min_score,
        only_reefer=reefer,
        shipper_only=shipper_only,
        hide_drivers=hide_drivers,
        muted_directions=[str(x) for x in muted],
        sort=sort,
        hot_only=hot,
        geo_corridor=geo,
        near_km=near,
        far_km=far,
        tonnage_min=tonnage_min,
        tonnage_max=tonnage_max,
        volume_min=volume_min,
        volume_max=volume_max,
        ppk_min=ppk_min,
        price_min=price_min,
        route_km_min=route_km_min,
        route_km_max=route_km_max,
        freshness_hours=freshness_hours,
        load_date_mode=_none_if_any(load_date_mode),
        loading=_none_if_any(loading),
        cargo_mode=_none_if_any(cargo_mode),
        payment=_none_if_any(payment),
        exact_from=exact_from,
        exact_to=exact_to,
        limit=limit,
        offset=offset,
    )
    from app.ingest import calc_price_per_km, why_rank

    for row in rows:
        # Fill route length from cities even when price is missing (common in TG/MAX)
        need_km = row.get("route_km") is None and row.get("from_city") and row.get("to_city")
        need_ppk = row.get("price") and row.get("price_per_km") is None
        if need_km or need_ppk:
            route_km, ppk = calc_price_per_km(
                row.get("price"), row.get("from_city"), row.get("to_city")
            )
            if route_km is not None and row.get("route_km") is None:
                row["route_km"] = route_km
            if ppk is not None and row.get("price_per_km") is None:
                row["price_per_km"] = ppk
        row["why"] = why_rank(
            score=int(row.get("score") or 0),
            km_from=row.get("km_from"),
            km_to=row.get("km_to"),
            near_km=near,
            source=str(row.get("source") or ""),
            scraped_at=row.get("scraped_at"),
        )
    filter_reasons: list[str] = []
    channel_labels = {"telegram": "Telegram", "max": "MAX", "sites": "Агрегаторы", "all": "Все"}
    if not rows:
        if channel_key in channel_labels and channel_key != "all":
            filter_reasons.append(f"вкладка «{channel_labels[channel_key]}»")
        elif source:
            filter_reasons.append(f"источник «{source}»")
        if shipper_only:
            filter_reasons.append("без водителей")
        if min_score > 40:
            filter_reasons.append(f"скор ≥ {min_score}")
        if hot:
            filter_reasons.append("только горячие")
        if reefer:
            filter_reasons.append("только реф")
        if frm or to:
            filter_reasons.append("узкий маршрут")
        if tonnage_min is not None or tonnage_max is not None:
            filter_reasons.append("вес")
        if ppk_min is not None:
            filter_reasons.append("ставка ₽/км")
        if freshness_hours is not None:
            filter_reasons.append("свежесть")
        if _none_if_any(cargo_mode):
            filter_reasons.append("FTL/LTL")
        if _none_if_any(loading):
            filter_reasons.append("тип загрузки")
        if geo:
            filter_reasons.append(f"коридор {int(near)}/{int(far)} км от базы «{base_city}»")
        if not filter_reasons:
            filter_reasons.append("нет свежих заявок — нажмите «Обновить»")
    if sort == "ppk":
        rank_explain = (
            f"Сорт: дороже ₽/км (выше оплата). База «{base_city}», коридор {int(near)}/{int(far)} км."
        )
    elif sort == "near":
        rank_explain = f"Сорт: ближе к базе «{base_city}». Коридор {int(near)}/{int(far)} км."
    elif sort == "score":
        rank_explain = f"Сорт: выше скор. База «{base_city}», коридор {int(near)}/{int(far)} км."
    elif sort == "route":
        rank_explain = f"Сорт: короче маршрут. База «{base_city}»."
    else:
        rank_explain = (
            f"Сорт: по дате публикации. "
            f"База «{base_city}», коридор {int(near)}/{int(far)} км."
        )
    return {
        "items": rows,
        "count": len(rows),
        "filter_reasons": filter_reasons,
        "rank_explain": rank_explain,
        "near_km": near,
        "far_km": far,
        "base": base_city,
        "muted_directions": muted,
        "channel": channel_key,
        "filters": {
            "tonnage_min": tonnage_min,
            "tonnage_max": tonnage_max,
            "volume_min": volume_min,
            "volume_max": volume_max,
            "ppk_min": ppk_min,
            "price_min": price_min,
            "route_km_min": route_km_min,
            "route_km_max": route_km_max,
            "freshness_hours": freshness_hours,
            "load_date_mode": load_date_mode or "any",
            "loading": loading or "any",
            "cargo_mode": cargo_mode or "any",
            "payment": payment or "any",
        },
    }


@app.get("/api/profile")
async def get_profile() -> dict[str, Any]:
    profile = await db.get_json_setting("truck_profile", {})
    muted = await db.get_json_setting("muted_directions", [])
    return {"truck_profile": profile or {}, "muted_directions": muted or []}


@app.post("/api/profile", dependencies=[Depends(require_write_token)])
async def set_profile(profile: TruckProfile) -> dict[str, Any]:
    prev = await db.get_json_setting("truck_profile", {})
    if not isinstance(prev, dict):
        prev = {}
    data = {k: v for k, v in profile.model_dump().items() if v not in (None, "", False)}
    if profile.backhaul:
        data["backhaul"] = True
    await db.set_json_setting("truck_profile", data)
    old_base = str(prev.get("base") or "москва").strip().lower() or "москва"
    new_base = str(data.get("base") or old_base).strip().lower() or "москва"
    km_info: dict[str, Any] = {}
    if new_base != old_base:
        from app.ingest import recompute_km_from_base

        km_info = await recompute_km_from_base(db, new_base)
    return {"ok": True, "truck_profile": data, "km_recompute": km_info}


@app.post("/api/mute", dependencies=[Depends(require_write_token)])
async def mute_direction(body: MuteIn) -> dict[str, Any]:
    muted = await db.get_json_setting("muted_directions", [])
    if not isinstance(muted, list):
        muted = []
    d = body.direction.lower().strip()
    if d not in muted:
        muted.append(d)
    await db.set_json_setting("muted_directions", muted)
    return {"ok": True, "muted_directions": muted}


@app.delete("/api/mute", dependencies=[Depends(require_write_token)])
async def clear_mutes(direction: str | None = Query(None)) -> dict[str, Any]:
    if direction:
        muted = await db.get_json_setting("muted_directions", [])
        if not isinstance(muted, list):
            muted = []
        d = direction.lower().strip()
        muted = [x for x in muted if str(x).lower().strip() != d]
        await db.set_json_setting("muted_directions", muted)
        return {"ok": True, "muted_directions": muted}
    await db.set_json_setting("muted_directions", [])
    return {"ok": True, "muted_directions": []}


@app.post("/api/maintenance/reparse-kinds", dependencies=[Depends(require_write_token)])
async def reparse_kinds(limit: int = Query(500, ge=1, le=5000)) -> dict[str, Any]:
    """Upgrade cargo-like other rows with route+tonnage to shipper."""
    from app.parse import parse_load

    assert db._db is not None
    cur = await db._db.execute(
        "SELECT id, body, kind FROM loads "
        "WHERE IFNULL(kind,'other') IN ('other','') "
        "ORDER BY scraped_at DESC LIMIT ?",
        (limit,),
    )
    rows = await cur.fetchall()
    updated = 0
    for r in rows:
        parsed = parse_load(r["body"] or "")
        new_kind = parsed.kind
        if new_kind == "other" and parsed.from_city and parsed.to_city and parsed.tonnage is not None:
            new_kind = "shipper"
        if new_kind and new_kind != (r["kind"] or ""):
            await db._db.execute("UPDATE loads SET kind=? WHERE id=?", (new_kind, r["id"]))
            updated += 1
    await db._db.commit()
    return {"ok": True, "scanned": len(rows), "updated": updated}


@app.post("/api/maintenance/backup", dependencies=[Depends(require_write_token)])
async def backup_db() -> dict[str, Any]:
    """Copy SQLite DB to /data/backups/hub-YYYYmmdd-HHMMSS.db"""
    import shutil
    from datetime import datetime, timezone

    src = config.DB_PATH
    if not src.exists():
        return {"ok": False, "error": "db_missing"}
    dest_dir = src.parent / "backups"
    dest_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    dest = dest_dir / f"hub-{stamp}.db"
    shutil.copy2(src, dest)
    old = sorted(dest_dir.glob("hub-*.db"), key=lambda p: p.stat().st_mtime, reverse=True)
    for p in old[10:]:
        try:
            p.unlink()
        except Exception:
            pass
    return {"ok": True, "path": str(dest), "size": dest.stat().st_size}


@app.post("/api/scrape", dependencies=[Depends(require_write_token)])
async def scrape_now(quick: bool = True) -> dict[str, Any]:
    """Start a scrape and return immediately (does not wait for boards)."""
    return worker.start_manual(quick=quick)


@app.get("/api/scrape/status")
async def scrape_status() -> dict[str, Any]:
    return worker.manual_status()


@app.post("/api/tg/qr", dependencies=[Depends(require_write_token)])
async def tg_qr_start() -> dict[str, Any]:
    from app import tg_login

    return await tg_login.start_qr()


@app.post("/api/tg/qr/wait", dependencies=[Depends(require_write_token)])
async def tg_qr_wait(timeout: float = Query(120, ge=30, le=300)) -> dict[str, Any]:
    from app import tg_login

    return await tg_login.wait_qr(timeout=timeout)


@app.post("/api/tg/qr/password", dependencies=[Depends(require_write_token)])
async def tg_qr_password(body: TgPasswordIn) -> dict[str, Any]:
    from app import tg_login

    return await tg_login.submit_2fa(body.password)


@app.post("/api/tg/restart", dependencies=[Depends(require_write_token)])
async def tg_restart() -> dict[str, Any]:
    global tg
    if tg:
        try:
            await tg.stop()
        except Exception:
            pass
        tg = None
    if not (config.ENABLE_TG and config.API_ID and config.API_HASH):
        return {"ok": False, "error": "tg_disabled"}
    from app.scrapers.telegram_src import TelegramIngest

    tg = TelegramIngest(db)
    await tg.start()
    return {"ok": True}


@app.get("/tg-login")
async def tg_login_page() -> FileResponse:
    return FileResponse(WEB / "tg-login.html")


@app.get("/")
async def index() -> Response:
    html = (WEB / "index.html").read_text(encoding="utf-8")
    token = ""
    if config.HUB_INJECT_UI_TOKEN and config.HUB_WRITE_TOKEN:
        token = config.HUB_WRITE_TOKEN
    html = html.replace("{{HUB_WRITE_TOKEN}}", token)
    html = html.replace(
        "{{WRITE_TOKEN_REQUIRED}}",
        "1" if config.HUB_WRITE_TOKEN else "0",
    )
    return HTMLResponse(html)


app.mount("/static", StaticFiles(directory=str(WEB)), name="static")


def run() -> None:
    import uvicorn

    uvicorn.run(
        "app.main:app",
        host=config.HOST,
        port=config.PORT,
        reload=False,
    )


if __name__ == "__main__":
    run()
