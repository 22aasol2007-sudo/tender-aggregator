from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.api import router
from app.config import settings
from app.database import SessionLocal, init_db
from app.services.auth import ensure_default_admin
from app.services.http_client import close_client
from app.services.scheduler import start_scheduler, stop_scheduler
from app.services.seed import seed_if_empty, seed_presets


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    db = SessionLocal()
    try:
        ensure_default_admin(db)
        if settings.seed_if_empty:
            seed_if_empty(db)
        seed_presets(db)
    finally:
        db.close()
    start_scheduler()
    yield
    stop_scheduler()
    await close_client()


app = FastAPI(title=settings.app_name, lifespan=lifespan)
app.add_middleware(GZipMiddleware, minimum_size=500)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(router, prefix="/api")

FRONTEND_DIST = Path(__file__).resolve().parents[2] / "frontend" / "dist"
if FRONTEND_DIST.exists():
    app.mount("/assets", StaticFiles(directory=FRONTEND_DIST / "assets"), name="assets")

    @app.get("/{full_path:path}")
    async def spa(full_path: str):  # noqa: ARG001
        index = FRONTEND_DIST / "index.html"
        if index.exists():
            return FileResponse(index)
        return {"detail": "Frontend not built"}
