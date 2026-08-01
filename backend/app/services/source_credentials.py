"""DB-backed API credentials for commercial scrape sources.

Rule: non-empty DB values win over env (`settings.*`). Env is fallback.
Tokens are never logged and are masked in API responses.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any

from sqlalchemy.orm import Session

from app.config import settings
from app.database import SessionLocal
from app.models import SourceApiCredential

logger = logging.getLogger(__name__)

# source_id → (label, settings_url_attr, settings_token_attr)
API_SOURCES: dict[str, tuple[str, str, str]] = {
    "contour": ("Контур.Закупки", "contour_api_url", "contour_api_token"),
    "tenderplan": ("Tenderplan", "tenderplan_api_url", "tenderplan_api_token"),
    "tenderland": ("Tenderland", "tenderland_api_url", "tenderland_api_token"),
    "synapse": ("Synapse", "synapse_api_url", "synapse_api_token"),
}

_CACHE_TTL = 30.0
_cache: dict[str, tuple[str | None, str | None, float]] = {}


@dataclass(frozen=True)
class ResolvedCreds:
    api_url: str | None
    api_token: str | None
    url_from_db: bool
    token_from_db: bool


def invalidate_credentials_cache(source: str | None = None) -> None:
    if source is None:
        _cache.clear()
    else:
        _cache.pop(source, None)


def mask_token(token: str | None) -> str | None:
    if not token:
        return None
    if len(token) <= 4:
        return "••••"
    return f"••••{token[-4:]}"


def _env_pair(source: str) -> tuple[str | None, str | None]:
    meta = API_SOURCES.get(source)
    if not meta:
        return None, None
    _, url_attr, token_attr = meta
    url = getattr(settings, url_attr, None) or None
    token = getattr(settings, token_attr, None) or None
    if isinstance(url, str):
        url = url.strip() or None
    if isinstance(token, str):
        token = token.strip() or None
    return url, token


def _merge_row(
    source: str,
    row: SourceApiCredential | None,
) -> ResolvedCreds:
    env_url, env_token = _env_pair(source)
    db_url = (row.api_url or "").strip() or None if row else None
    db_token = (row.api_token or "").strip() or None if row else None
    url_from_db = bool(db_url)
    token_from_db = bool(db_token)
    return ResolvedCreds(
        api_url=db_url if url_from_db else env_url,
        api_token=db_token if token_from_db else env_token,
        url_from_db=url_from_db,
        token_from_db=token_from_db,
    )


def resolve_credentials(source: str, db: Session | None = None) -> tuple[str | None, str | None]:
    """Return (api_url, api_token). DB non-empty fields override env."""
    if source not in API_SOURCES:
        return None, None

    now = time.monotonic()
    hit = _cache.get(source)
    if hit and now - hit[2] < _CACHE_TTL:
        return hit[0], hit[1]

    own_session = db is None
    session = db or SessionLocal()
    try:
        row = (
            session.query(SourceApiCredential)
            .filter(SourceApiCredential.source == source)
            .one_or_none()
        )
        resolved = _merge_row(source, row)
        _cache[source] = (resolved.api_url, resolved.api_token, now)
        return resolved.api_url, resolved.api_token
    except Exception:  # noqa: BLE001
        logger.exception("Failed to load API credentials for source=%s", source)
        return _env_pair(source)
    finally:
        if own_session:
            session.close()


def list_credential_status(db: Session) -> list[dict[str, Any]]:
    rows = {
        r.source: r
        for r in db.query(SourceApiCredential)
        .filter(SourceApiCredential.source.in_(list(API_SOURCES.keys())))
        .all()
    }
    out: list[dict[str, Any]] = []
    for source, (label, _, _) in API_SOURCES.items():
        resolved = _merge_row(source, rows.get(source))
        configured = bool(resolved.api_url and resolved.api_token)
        out.append(
            {
                "source": source,
                "label": label,
                "api_url": resolved.api_url,
                "token_configured": bool(resolved.api_token),
                "token_masked": mask_token(resolved.api_token),
                "configured": configured,
                "url_from_db": resolved.url_from_db,
                "token_from_db": resolved.token_from_db,
                "updated_at": rows[source].updated_at if source in rows else None,
            }
        )
    return out


def upsert_credential(
    db: Session,
    *,
    source: str,
    api_url: str | None = None,
    api_token: str | None = None,
    clear_token: bool = False,
    user_id: int | None = None,
) -> dict[str, Any]:
    if source not in API_SOURCES:
        raise ValueError(f"Unknown source: {source}")

    row = (
        db.query(SourceApiCredential)
        .filter(SourceApiCredential.source == source)
        .one_or_none()
    )
    if row is None:
        row = SourceApiCredential(source=source)
        db.add(row)

    if api_url is not None:
        cleaned = api_url.strip()
        row.api_url = cleaned or None

    if clear_token:
        row.api_token = None
    elif api_token is not None:
        cleaned_token = api_token.strip()
        if cleaned_token:
            row.api_token = cleaned_token
        # empty string → keep existing token (do not wipe on accidental blank save)

    if user_id is not None:
        row.updated_by_user_id = user_id

    db.commit()
    db.refresh(row)
    invalidate_credentials_cache(source)
    logger.info(
        "Updated scrape API credentials source=%s url_set=%s token_set=%s",
        source,
        bool(row.api_url),
        bool(row.api_token),
    )
    # Return masked status for this source only
    statuses = {s["source"]: s for s in list_credential_status(db)}
    return statuses[source]


async def test_credential_connection(api_url: str, api_token: str) -> dict[str, Any]:
    """Cheap GET with Bearer token; does not log the token."""
    import httpx

    url = (api_url or "").strip()
    token = (api_token or "").strip()
    if not url or not token:
        return {"ok": False, "status_code": None, "detail": "Нужны URL и токен"}

    headers = {
        "Accept": "application/json",
        "Authorization": f"Bearer {token}",
        "User-Agent": settings.user_agent,
    }
    try:
        async with httpx.AsyncClient(timeout=12.0, follow_redirects=True) as client:
            resp = await client.get(url, headers=headers)
        ok = 200 <= resp.status_code < 400
        return {
            "ok": ok,
            "status_code": resp.status_code,
            "detail": "OK" if ok else f"HTTP {resp.status_code}",
        }
    except httpx.HTTPError as exc:
        return {"ok": False, "status_code": None, "detail": type(exc).__name__}
