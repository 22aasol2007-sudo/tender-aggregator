from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import certifi
import httpx

from app.config import settings

_client: httpx.AsyncClient | None = None
# (cached_at, status, body_bytes, headers) — body is already decoded UTF-8 text as bytes
_cache: dict[str, tuple[float, int, bytes, dict[str, str]]] = {}
_cache_lock = asyncio.Lock()

_HOP_BY_HOP = {
    "content-encoding",
    "content-length",
    "transfer-encoding",
    "connection",
    "keep-alive",
}


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
                "Accept-Encoding": "gzip, deflate, br",
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


def _cacheable_headers(headers: httpx.Headers) -> dict[str, str]:
    """Strip compression/length headers; force UTF-8 charset for replay."""
    out: dict[str, str] = {}
    for key, value in headers.items():
        low = key.lower()
        if low in _HOP_BY_HOP:
            continue
        if low == "content-type":
            base = value.split(";")[0].strip() or "text/html"
            out[key] = f"{base}; charset=utf-8"
        else:
            out[key] = value
    if "content-type" not in {k.lower() for k in out}:
        out["Content-Type"] = "text/html; charset=utf-8"
    return out


async def _get_with_retries(
    url: str,
    *,
    headers: dict[str, str] | None = None,
) -> httpx.Response:
    """GET with exponential backoff on transport errors and 429/502/503/504."""
    client = get_client()
    attempts = max(1, settings.http_retries)
    retry_statuses = set(settings.http_retry_statuses or [429, 502, 503, 504])
    last_exc: Exception | None = None
    last_resp: httpx.Response | None = None

    for attempt in range(1, attempts + 1):
        try:
            resp = await client.get(url, headers=headers)
            if resp.status_code in retry_statuses and attempt < attempts:
                last_resp = resp
                delay = min(8.0, 0.6 * (2 ** (attempt - 1)))
                retry_after = resp.headers.get("Retry-After")
                if retry_after:
                    try:
                        delay = max(delay, min(30.0, float(retry_after)))
                    except ValueError:
                        pass
                await asyncio.sleep(delay)
                continue
            return resp
        except (httpx.HTTPError, TimeoutError, OSError) as exc:
            last_exc = exc
            if attempt >= attempts:
                break
            await asyncio.sleep(min(8.0, 0.6 * (2 ** (attempt - 1))))

    if last_resp is not None:
        return last_resp
    assert last_exc is not None
    raise last_exc


async def cached_get(
    url: str,
    *,
    headers: dict[str, str] | None = None,
    ttl: float | None = None,
) -> httpx.Response:
    """GET with in-memory TTL cache (decoded UTF-8 body + status)."""
    cache_ttl = settings.http_cache_ttl_seconds if ttl is None else ttl
    now = time.monotonic()
    async with _cache_lock:
        hit = _cache.get(url)
        if hit and now - hit[0] < cache_ttl:
            _cached_at, status, body, hdrs = hit
            request = get_client().build_request("GET", url, headers=headers)
            return httpx.Response(
                status,
                content=body,
                request=request,
                headers=hdrs,
                encoding="utf-8",
            )

    resp = await _get_with_retries(url, headers=headers)
    # Cache successful and empty-ish responses briefly to avoid hammering
    if resp.status_code < 500 and cache_ttl > 0:
        # Decode once via httpx, store UTF-8 bytes so replay never re-gunzips
        try:
            body = resp.text.encode("utf-8")
        except Exception:
            body = resp.content
        hdrs = _cacheable_headers(resp.headers)
        async with _cache_lock:
            _cache[url] = (now, resp.status_code, body, hdrs)
            if len(_cache) > 500:
                oldest = sorted(_cache.items(), key=lambda x: x[1][0])[:100]
                for key, _ in oldest:
                    _cache.pop(key, None)
    return resp
