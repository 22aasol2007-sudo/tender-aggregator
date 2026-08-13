"""Write-API token gate for public hub URL."""

from __future__ import annotations

from fastapi import Header, HTTPException, Query, Request

from app import config


async def require_write_token(
    request: Request,
    x_hub_token: str | None = Header(None, alias="X-Hub-Token"),
    token: str | None = Query(None),
) -> None:
    expected = (config.HUB_WRITE_TOKEN or "").strip()
    if not expected:
        # Dev / unset: leave open (local). Production should set HUB_WRITE_TOKEN.
        return
    provided = (x_hub_token or token or "").strip()
    if not provided:
        auth = request.headers.get("Authorization") or ""
        if auth.lower().startswith("bearer "):
            provided = auth[7:].strip()
    if provided != expected:
        raise HTTPException(status_code=401, detail="write_token_required")
