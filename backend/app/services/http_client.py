from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import certifi
import httpx

from app.config import settings

_client: httpx.AsyncClient | None = None
_cache: dict[str, tuple[float, int, str, dict[str, str]]] = {}
_cache_lock = asyncio.Lock()


def _ssl_verify() -> bool | str:
    if not settings.http_verify_ssl:
        return False
    return certifi.where()


def get_client() -> httpx.AsyncClient:
    global _client
    if _client is None or _client.is_closed:
        _client = httpx.AsyncClient(
            headers={
                "User-Agent": settings.user_agent,
                "Accept-Language": "ru-RU,ru;q=0.9,en;q=0.8",
            },
            timeout=settings.http_timeout,
            follow_redirects=True,
            verify=_ssl_verify(),
            limits=httpx.Limits(
                max_connections=settings.http_max_connections,
                max_keepalive_connections=settings.http_max_keepalive,
            ),
        )
    return _client


async def close_client() -> None:
    global _client
    if _client is not None and not _client.is_closed:
        await _client.aclose()
    _client = None


@asynccontextmanager
async def shared_client() -> AsyncIterator[httpx.AsyncClient]:
    yield get_client()


async def cached_get(
    url: str,
    *,
    headers: dict[str, str] | None = None,
    ttl: float | None = None,
) -> httpx.Response:
    """GET with in-memory TTL cache (body text + status)."""
    cache_ttl = settings.http_cache_ttl_seconds if ttl is None else ttl
    now = time.monotonic()
    async with _cache_lock:
        hit = _cache.get(url)
        if hit and now - hit[0] < cache_ttl:
            cached_at, status, text, hdrs = hit
            request = get_client().build_request("GET", url, headers=headers)
            return httpx.Response(
                status,
                content=text.encode("utf-8"),
                request=request,
                headers=hdrs,
            )

    client = get_client()
    resp = await client.get(url, headers=headers)
    # Cache successful and empty-ish responses briefly to avoid hammering
    if resp.status_code < 500 and cache_ttl > 0:
        async with _cache_lock:
            _cache[url] = (
                now,
                resp.status_code,
                resp.text,
                dict(resp.headers),
            )
            # Bound cache size
            if len(_cache) > 500:
                oldest = sorted(_cache.items(), key=lambda x: x[1][0])[:100]
                for key, _ in oldest:
                    _cache.pop(key, None)
    return resp
