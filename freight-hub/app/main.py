from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, File, Form, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

import app._bootstrap  # noqa: F401
from app import config
from app.auth import require_write_token
from app.db import HubDB
from app.rate_analyze import RateAnalyzer
from app.screenshot_offer import extract_from_screenshot, resolve_analyze_targets, vision_configured
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
    try:
        from app.observability import init_sentry

        init_sentry()
    except Exception:
        pass
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
    # Promote route-bearing messenger "other" → shipper (short TG ads) — background
    async def _kind_upgrade() -> None:
        try:
            from freight_core.parse import parse_load

            assert db._db is not None
            cur = await db._db.execute(
                "SELECT id, body, kind FROM loads "
                "WHERE IFNULL(kind,'other') IN ('other','') "
                "AND source IN ('telegram','max','tg_public') "
                "ORDER BY scraped_at DESC LIMIT 3000"
            )
            rows = await cur.fetchall()
            up = 0
            for r in rows:
                p = parse_load(r["body"] or "")
                if p.from_city and p.to_city and (r["kind"] or "other") in {"other", ""}:
                    await db._db.execute("UPDATE loads SET kind=? WHERE id=?", ("shipper", r["id"]))
                    up += 1
            if up:
                await db._db.commit()
                log.info("startup kind upgrade: %s rows → shipper", up)
        except Exception as exc:
            log.warning("startup kind upgrade failed: %s", exc)

    asyncio.create_task(_kind_upgrade())
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
    # Unit economics (override env defaults)
    diesel_rub_per_l: float | None = None
    fuel_l_per_100km: float | None = None
    driver_day_rub: float | None = None
    tax_pct: float | None = None  # 0.35 or 35
    amortization_pct: float | None = None
    target_net_min: float | None = None
    target_net_max: float | None = None
    load_unload_hours: float | None = None
    backhaul_radius_km: float | None = None


def _econ_overrides_from_profile(profile: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(profile, dict):
        return {}
    keys = (
        "diesel_rub_per_l",
        "fuel_l_per_100km",
        "driver_day_rub",
        "tax_pct",
        "amortization_pct",
        "target_net_min",
        "target_net_max",
        "load_unload_hours",
        "backhaul_radius_km",
        "avg_speed_kmh",
    )
    out: dict[str, Any] = {}
    for k in keys:
        v = profile.get(k)
        if v is None or v == "":
            continue
        try:
            out[k] = float(v)
        except (TypeError, ValueError):
            continue
    for pct_key in ("tax_pct", "amortization_pct"):
        if pct_key in out and out[pct_key] > 1.0:
            out[pct_key] = out[pct_key] / 100.0
    return out


async def _truck_profile_dict() -> dict[str, Any]:
    try:
        truck = await db.get_json_setting("truck_profile", {})
        return truck if isinstance(truck, dict) else {}
    except Exception:
        return {}


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

    # Silent messenger channels — listening but no adds → warn light + TG alert
    drought_sec = float(getattr(config, "MESSENGER_DROUGHT_HOURS", 2)) * 3600
    for src, label, alive, status_key in (
        ("telegram", "Telegram", tg_alive, "tg"),
        ("max", "MAX", mx_alive, "max"),
    ):
        if not alive:
            continue
        try:
            last = float((await db.get_setting(f"last_ingest_{src}")) or 0)
        except Exception:
            last = 0.0
        if last and now - last > drought_sec:
            hours = (now - last) / 3600
            hints.append(f"{label}: нет новых заявок уже {int(hours)} ч")
            if status_key == "tg" and tg_status == "on":
                tg_status = "warn"
            if status_key == "max" and max_status == "on":
                max_status = "warn"
            try:
                from app.alerts import maybe_alert_messenger_drought

                await maybe_alert_messenger_drought(
                    source=label, hours=hours, listening=True
                )
            except Exception:
                pass

    if st["total"] < 30:
        hints.append("Мало заявок в ленте — обновите источники.")

    # Freshness clock = last successful add / scrape, NOT listener heartbeat
    latest_ts = 0.0
    for key in ("telegram", "max"):
        try:
            latest_ts = max(latest_ts, float((await db.get_setting(f"last_ingest_{key}")) or 0))
        except Exception:
            pass
    for run in (st.get("recent_runs") or [])[:8]:
        try:
            if run.get("ok") and (run.get("added") or run.get("updated")):
                latest_ts = max(latest_ts, float(run.get("finished_at") or 0))
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
        # watched = unique channels (not ±id variants); never add failed twice
        mx_total = max(mx_watched, mx_ok + mx_failed)
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

    from app.ingest_metrics import snapshot as ingest_snapshot

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
        "ingest_metrics": {
            "1h": ingest_snapshot(hours=1),
            "24h": ingest_snapshot(hours=24),
        },
        "db": {
            "backend": "postgres" if getattr(config, "DATABASE_URL", "") else "sqlite",
            "path": str(config.DB_PATH),
            "postgres_url_set": bool(getattr(config, "DATABASE_URL", "")),
        },
        "updated_ago_sec": max(0, int(now - latest_ts)) if latest_ts else 0,
        "hints": hints,
        "tg_need_login": tg_need_login,
        "tg_down": not tg_alive,
        "zero_add_streaks": zero_streaks if isinstance(zero_streaks, dict) else {},
        "write_token_required": bool(config.HUB_WRITE_TOKEN),
        "public_url": getattr(config, "PUBLIC_URL", None) or "https://freight-edge.vercel.app",
        "api_via": "vercel_proxy",
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


@app.get("/api/analyze/route")
async def analyze_route(
    destination: str = Query(..., min_length=2, max_length=80),
    base: str | None = Query(None, max_length=80),
    from_city: str | None = Query(None, max_length=80),
    offer_rub: float | None = Query(None, ge=0, le=50_000_000),
    tonnage: float | None = Query(None, ge=0, le=100),
    body: str | None = Query(None, max_length=32),
    route_km: float | None = Query(None, ge=1, le=20_000),
    live: bool = Query(True),
) -> dict[str, Any]:
    """Backhaul liquidity + suggested min rate for base→destination."""
    truck = await _truck_profile_dict()
    base_city = (base or "").strip() or str(truck.get("base") or "москва")
    analyzer = RateAnalyzer(db)
    return await analyzer.analyze(
        base=base_city,
        destination=destination.strip(),
        offer_rub=offer_rub,
        tonnage=tonnage,
        body=body,
        live_probe=live,
        route_km_override=route_km,
        from_city=(from_city or "").strip() or None,
        params_override=_econ_overrides_from_profile(truck),
    )


@app.get("/api/analyze/ranking")
async def analyze_ranking(
    base: str | None = Query(None, max_length=80),
    days: float = Query(7, ge=1, le=30),
    limit: int = Query(25, ge=5, le=50),
) -> dict[str, Any]:
    base_city = (base or "").strip()
    if not base_city:
        try:
            truck = await db.get_json_setting("truck_profile", {})
            if isinstance(truck, dict):
                base_city = str(truck.get("base") or "москва")
            else:
                base_city = "москва"
        except Exception:
            base_city = "москва"
    rows = await db.backhaul_city_ranking(base=base_city, days=days, limit=limit)
    return {"ok": True, "base": base_city, "days": days, "ranking": rows}


async def _profile_base() -> str:
    try:
        truck = await db.get_json_setting("truck_profile", {})
        if isinstance(truck, dict):
            return str(truck.get("base") or "москва").strip() or "москва"
    except Exception:
        pass
    return "москва"


@app.get("/api/analyze/vision-status")
async def analyze_vision_status() -> dict[str, Any]:
    return {"ok": True, **vision_configured()}


@app.post("/api/analyze/screenshot")
async def analyze_screenshot(
    file: UploadFile = File(...),
    base: str | None = Form(None),
    live: bool = Form(True),
) -> dict[str, Any]:
    """Upload freight-board screenshot → extract route/rate → backhaul profitability."""
    try:
        raw = await file.read()
        extracted = await extract_from_screenshot(raw, filename=file.filename)
        if not extracted.get("ok"):
            return {
                "ok": False,
                "error": extracted.get("error") or "Не удалось разобрать скрин",
                "extracted": extracted.get("fields") or {},
                "method": extracted.get("method"),
                "vision_ready": vision_configured(),
            }

        fields = extracted["fields"]
        base_city = (base or "").strip() or await _profile_base()
        targets = resolve_analyze_targets(fields, base=base_city)
        if not targets.get("destination"):
            return {
                "ok": False,
                "error": "На скрине не найден город выгрузки/погрузки",
                "extracted": fields,
                "method": extracted.get("method"),
            }

        truck = await _truck_profile_dict()
        analyzer = RateAnalyzer(db)
        analysis = await analyzer.analyze(
            base=targets["base"],
            destination=str(targets["destination"]),
            offer_rub=targets.get("offer_rub"),
            tonnage=targets.get("tonnage"),
            body=targets.get("body"),
            live_probe=live,
            route_km_override=targets.get("listed_route_km"),
            from_city=targets.get("from_city") or fields.get("from_city"),
            params_override=_econ_overrides_from_profile(truck),
        )
        advice = (analysis or {}).get("verdict")
        if not advice and analysis.get("ok") and not analysis.get("route_km"):
            advice = {
                "action": "skip",
                "label": "мимо",
                "tone": "skip",
                "text": "Нет километража — поправьте OCR (км) и пересчитайте.",
            }

        return {
            "ok": True,
            "method": extracted.get("method"),
            "extracted": fields,
            "targets": targets,
            "advice": advice,
            "analysis": analysis,
            "vision_ready": vision_configured(),
        }
    except Exception as exc:
        log.exception("analyze_screenshot failed: %s", exc)
        return {
            "ok": False,
            "error": "Не удалось разобрать скрин (сервер). Попробуйте ещё раз или заполните поля вручную.",
            "detail": str(exc)[:240],
            "vision_ready": vision_configured(),
        }


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
            kind=str(row.get("kind") or "") or None,
        )

    # Cross-source merge: one card per route_fp with source badges
    if rows:
        merged: list[dict[str, Any]] = []
        seen_fp: set[str] = set()
        for row in rows:
            fp = str(row.get("route_fp") or "")
            if not fp or fp in seen_fp:
                if fp and fp in seen_fp:
                    continue
                merged.append(row)
                continue
            seen_fp.add(fp)
            try:
                sibs = await db.find_route_siblings(
                    fp, within_sec=config.CROSS_DEDUP_HOURS * 3600, limit=8
                )
            except Exception:
                sibs = []
            sources = []
            for s in sibs:
                sources.append(
                    {
                        "source": s.get("source"),
                        "url": s.get("url"),
                        "score": s.get("score"),
                    }
                )
            if not sources:
                sources = [{"source": row.get("source"), "url": row.get("url"), "score": row.get("score")}]
            row["sources"] = sources
            row["source_count"] = len(sources)
            if len(sources) > 1:
                why = list(row.get("why") or [])
                why.append(f"{len(sources)} источника")
                row["why"] = why[:4]
            merged.append(row)
        rows = merged
    filter_reasons: list[str] = []
    outside_corridor: dict[str, Any] | None = None
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
            try:
                n_out = await db.count_outside_corridor(
                    sources=group_sources,
                    source=source if not group_sources else None,
                    near_km=near,
                    far_km=far,
                    min_score=min_score,
                )
            except Exception:
                n_out = 0
            if n_out > 0:
                label = channel_labels.get(channel_key, "Лента")
                outside_corridor = {
                    "count": n_out,
                    "label": label,
                    "near_km": near,
                    "far_km": far,
                    "base": base_city,
                    "message": f"{label}: {n_out} постов вне коридора {int(near)}/{int(far)} км",
                }
                filter_reasons = [outside_corridor["message"]]
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
        "outside_corridor": outside_corridor,
        "geo": geo,
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
    data = dict(prev)
    for k, v in profile.model_dump().items():
        if k == "backhaul":
            data["backhaul"] = bool(v)
            continue
        if v is None or v == "":
            continue
        if k in ("tax_pct", "amortization_pct") and isinstance(v, (int, float)) and float(v) > 1:
            data[k] = float(v) / 100.0
        else:
            data[k] = v
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


@app.post("/api/maintenance/reparse-routes", dependencies=[Depends(require_write_token)])
async def reparse_routes(
    days: float = Query(7, ge=0.5, le=30),
    limit: int = Query(2000, ge=1, le=8000),
) -> dict[str, Any]:
    """Re-split/reparse messenger posts (fixes «Фрязино→Москва» instead of «→Душанбе»)."""
    import time as _time

    from app.ingest import ingest_raw
    from app.models import RawLoad
    from freight_core.geo import distance_km
    from freight_core.parse import parse_load, parse_load_blocks

    assert db._db is not None
    cutoff = _time.time() - float(days) * 86400
    markers = (
        "душанбе",
        "ташкент",
        "бишкек",
        "алматы",
        "худжанд",
        "самарканд",
        "ашхабад",
    )
    # NOTE: SQLite LOWER() is ASCII-only — filter Cyrillic markers in Python.
    cur = await db._db.execute(
        """
        SELECT id, source, external_id, body, from_city, to_city, url, title, price, tonnage
        FROM loads
        WHERE source IN ('telegram','max','tg_public')
          AND scraped_at >= ?
        ORDER BY scraped_at DESC
        LIMIT ?
        """,
        (cutoff, limit),
    )
    raw_rows = [dict(r) for r in await cur.fetchall()]
    rows: list[dict[str, Any]] = []
    for r in raw_rows:
        blob = (r.get("body") or "").lower().replace("ё", "е")
        if any(m in blob for m in markers):
            rows.append(r)

    # Group by base external_id (strip #block suffix)
    groups: dict[tuple[str, str], dict[str, Any]] = {}
    for r in rows:
        ext = str(r["external_id"] or "")
        base_ext = ext.split("#", 1)[0]
        key = (str(r["source"]), base_ext)
        prev = groups.get(key)
        body = r.get("body") or ""
        if not prev or len(body) > len(prev.get("body") or ""):
            groups[key] = r

    fixed = 0
    created = 0
    deleted = 0
    examples: list[dict[str, Any]] = []

    for (source, base_ext), sample in groups.items():
        body = sample.get("body") or ""
        if not body.strip():
            continue
        blocks = parse_load_blocks(body)
        if not blocks:
            continue

        # Drop old rows for this message (single + split)
        del_cur = await db._db.execute(
            "DELETE FROM loads WHERE source=? AND (external_id=? OR external_id LIKE ?)",
            (source, base_ext, f"{base_ext}#%"),
        )
        deleted += int(del_cur.rowcount or 0)

        raw = RawLoad(
            source=source,
            external_id=base_ext,
            title=sample.get("title"),
            body=body,
            url=sample.get("url"),
            price=sample.get("price"),
            tonnage=sample.get("tonnage"),
            raw={"via": "reparse_routes"},
        )
        status = await ingest_raw(db, raw, min_score=0, scoring="browse", split_blocks=True)
        if status in {"added", "updated"}:
            fixed += 1
            if status == "added":
                created += 1
            if len(examples) < 8:
                routes = [
                    {"from": b.from_city, "to": b.to_city}
                    for b in blocks
                    if b.from_city or b.to_city
                ]
                examples.append({"external_id": base_ext, "routes": routes, "status": status})

    # Patch any remaining false Moscow destinations when CIS marker is in body
    patched = 0
    for r in raw_rows:
        to = (r.get("to_city") or "").lower().replace("ё", "е")
        blob = (r.get("body") or "").lower().replace("ё", "е")
        if to != "москва" or "душанбе" not in blob:
            continue
        p = parse_load(r["body"] or "")
        if not p.to_city or p.to_city == "москва":
            for b in parse_load_blocks(r["body"] or ""):
                if b.from_city and b.to_city and b.to_city != "москва":
                    if not r.get("from_city") or b.from_city == (r.get("from_city") or "").lower():
                        p = b
                        break
        if p.to_city and p.to_city != "москва":
            frm = p.from_city or r.get("from_city")
            to_city = p.to_city
            title = f"{frm or '?'} → {to_city or '?'}"
            km_from = distance_km(frm, "москва") if frm else None
            km_to = distance_km(to_city, "москва") if to_city else None
            await db._db.execute(
                """
                UPDATE loads SET from_city=?, to_city=?, title=?, km_from=?, km_to=?,
                  route_km=NULL, price_per_km=NULL, kind=COALESCE(NULLIF(?,''), kind)
                WHERE id=?
                """,
                (frm, to_city, title, km_from, km_to, p.kind or "", r["id"]),
            )
            patched += 1

    await db._db.commit()
    return {
        "ok": True,
        "scanned_messenger": len(raw_rows),
        "matched_markers": len(rows),
        "groups": len(groups),
        "fixed": fixed,
        "created_batches": created,
        "deleted_old": deleted,
        "patched_moscow": patched,
        "examples": examples,
    }


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


@app.get("/favicon.ico")
async def favicon() -> FileResponse:
    return FileResponse(WEB / "favicon.svg", media_type="image/svg+xml")


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
