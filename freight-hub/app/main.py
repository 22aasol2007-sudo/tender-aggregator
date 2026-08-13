from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

import app._bootstrap  # noqa: F401
from app import config
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

    st = await db.stats()
    tg_h = await db.get_tg_health()
    mx_raw = await db.get_setting("max_health")
    try:
        mx_h = _json.loads(mx_raw) if isinstance(mx_raw, str) and mx_raw else (mx_raw or {})
    except Exception:
        mx_h = {}
    if not isinstance(mx_h, dict):
        mx_h = {}
    hints: list[str] = []
    tg_alive = bool(tg and getattr(tg, "ok", False))
    if not tg_alive:
        if not config.API_ID or not config.API_HASH:
            hints.append("Нет API_ID/API_HASH — основной объём заявок идёт из Telegram.")
        else:
            note = str((tg_h or {}).get("note") or "")
            if "need_qr_login" in note or "two different IP" in note or "session_revoked" in note:
                hints.append("Telegram: сессия сброшена (два IP). Войдите заново: /tg-login")
            elif not (tg_h or {}).get("ok"):
                hints.append("Telegram не подключён / reconnect… (VPN?)")
    elif tg_h.get("failed_count"):
        hints.append(f"Не резолвится чатов: {tg_h.get('failed_count')} (см. tg_health).")
    mx_alive = bool(mx and getattr(mx, "ok", False) and mx_h.get("ok"))
    if config.ENABLE_MAX and not mx_alive:
        note = mx_h.get("note") or "off"
        if note in {"no_session", "disabled", "off"} or not mx_h:
            hints.append("MAX: нет сессии — запусти python login_max.py и отсканируй QR.")
        else:
            hints.append(f"MAX: {note}")
    if st["total"] < 30:
        hints.append(
            "Бесплатные агрегаторы отдают мало грузов. Нужен VPN + TG session для объёма."
        )
    return {
        "ok": True,
        "tg": bool(tg and getattr(tg, "ok", False)),
        "tg_configured": bool(config.API_ID and config.API_HASH),
        "tg_health": tg_h,
        "max": bool(mx and getattr(mx, "ok", False) and mx_h.get("ok")),
        "max_health": mx_h,
        "total_loads": st["total"],
        "by_source": st["by_source"],
        "hints": hints,
        "optimizations": {
            "parallel_scrape": True,
            "per_source_intervals": True,
            "cross_dedup_hours": config.CROSS_DEDUP_HOURS,
            "wal": True,
            "watchdog_sec": config.WATCHDOG_SEC,
        },
        "single_listener": "Hub owns Telethon; bot should use USE_HUB_INGEST=1",
    }


@app.get("/api/stats")
async def stats() -> dict[str, Any]:
    st = await db.stats()
    st["tg_health"] = await db.get_tg_health()
    return st


@app.get("/api/loads")
async def loads(
    q: str | None = None,
    source: str | None = None,
    body: str | None = Query(None, alias="body_type"),
    frm: str | None = Query(None, alias="from"),
    to: str | None = None,
    min_score: int = Query(40, ge=0, le=100),
    reefer: bool = False,
    shipper_only: bool = True,
    hide_drivers: bool = True,
    hot: bool = False,
    geo: bool = True,
    sort: str = Query("time", pattern="^(time|score)$"),
    limit: int = Query(200, ge=1, le=500),
    offset: int = Query(0, ge=0),
) -> dict[str, Any]:
    muted = await db.get_json_setting("muted_directions", [])
    if not isinstance(muted, list):
        muted = []
    profile = await db.get_json_setting("truck_profile", {})
    if not isinstance(profile, dict):
        profile = {}
    try:
        near = float(profile.get("radius") or 150)
    except (TypeError, ValueError):
        near = 150.0
    try:
        far = float(profile.get("radius_far") or profile.get("far_radius") or 1500)
    except (TypeError, ValueError):
        far = 1500.0
    rows = await db.list_loads(
        q=q,
        source=source,
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
        limit=limit,
        offset=offset,
    )
    return {"items": rows, "count": len(rows)}


@app.get("/api/profile")
async def get_profile() -> dict[str, Any]:
    profile = await db.get_json_setting("truck_profile", {})
    muted = await db.get_json_setting("muted_directions", [])
    return {"truck_profile": profile or {}, "muted_directions": muted or []}


@app.post("/api/profile")
async def set_profile(profile: TruckProfile) -> dict[str, Any]:
    data = {k: v for k, v in profile.model_dump().items() if v not in (None, "", False)}
    if profile.backhaul:
        data["backhaul"] = True
    await db.set_json_setting("truck_profile", data)
    return {"ok": True, "truck_profile": data}


@app.post("/api/mute")
async def mute_direction(body: MuteIn) -> dict[str, Any]:
    muted = await db.get_json_setting("muted_directions", [])
    if not isinstance(muted, list):
        muted = []
    d = body.direction.lower().strip()
    if d not in muted:
        muted.append(d)
    await db.set_json_setting("muted_directions", muted)
    return {"ok": True, "muted_directions": muted}


@app.delete("/api/mute")
async def clear_mutes() -> dict[str, Any]:
    await db.set_json_setting("muted_directions", [])
    return {"ok": True, "muted_directions": []}


@app.post("/api/scrape")
async def scrape_now(quick: bool = True) -> dict[str, Any]:
    """Start a scrape and return immediately (does not wait for boards)."""
    return worker.start_manual(quick=quick)


@app.get("/api/scrape/status")
async def scrape_status() -> dict[str, Any]:
    return worker.manual_status()


@app.post("/api/tg/qr")
async def tg_qr_start() -> dict[str, Any]:
    from app import tg_login

    return await tg_login.start_qr()


@app.post("/api/tg/qr/wait")
async def tg_qr_wait(timeout: float = Query(120, ge=30, le=300)) -> dict[str, Any]:
    from app import tg_login

    return await tg_login.wait_qr(timeout=timeout)


@app.post("/api/tg/qr/password")
async def tg_qr_password(body: TgPasswordIn) -> dict[str, Any]:
    from app import tg_login

    return await tg_login.submit_2fa(body.password)


@app.post("/api/tg/restart")
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
async def index() -> FileResponse:
    return FileResponse(WEB / "index.html")


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
