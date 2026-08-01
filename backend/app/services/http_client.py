from __future__ import annotations

import asyncio
import os
import random
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from urllib.parse import urlparse

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

# Hosts that are often slow / flaky from abroad (US→RU); give them more read budget.
_RU_SLOW_HOST_SUFFIXES = (
    "zakupki.gov.ru",
    "roseltorg.ru",
    "fabrikant.ru",
    "b2b-center.ru",
    "rostender.info",
    "rts-tender.ru",
    "sberbank-ast.ru",
    "tektorg.ru",
    "etpgpb.ru",
    "otc.ru",
    "torgi.gov.ru",
    "fedresurs.ru",
)


def _ssl_verify() -> bool | str:
    if not settings.http_verify_ssl:
        return False
    return certifi.where()


def _resolve_proxy() -> str | None:
    """Explicit scrape proxy wins; else honour HTTP(S)_PROXY / ALL_PROXY."""
    for key in (
        "scrape_proxy_url",
        "https_proxy",
        "http_proxy",
        "all_proxy",
    ):
        val = getattr(settings, key, None)
        if val and str(val).strip():
            return str(val).strip()
    # OS env fallback (httpx also trusts these when trust_env=True)
    for env_key in ("SCRAPE_PROXY_URL", "HTTPS_PROXY", "HTTP_PROXY", "ALL_PROXY"):
        val = os.environ.get(env_key) or os.environ.get(env_key.lower())
        if val and val.strip():
            return val.strip()
    return None


def _default_headers() -> dict[str, str]:
    return {
        "User-Agent": settings.user_agent,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7",
        "Accept-Encoding": "gzip, deflate, br",
        "Cache-Control": "no-cache",
        "Pragma": "no-cache",
        "Upgrade-Insecure-Requests": "1",
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "none",
        "Sec-Fetch-User": "?1",
    }


def _build_timeout() -> httpx.Timeout:
    """Split connect (fail fast on blackhole) vs read (slow EIS/ETP pages)."""
    connect = float(settings.http_connect_timeout)
    read = float(settings.http_read_timeout or settings.http_timeout)
    write = min(read, 30.0)
    pool = min(connect, 10.0)
    return httpx.Timeout(connect=connect, read=read, write=write, pool=pool)


def _timeout_for_url(url: str) -> httpx.Timeout:
    """Longer read budget for known RU public hosts when scraping from abroad."""
    host = (urlparse(url).hostname or "").lower()
    base = _build_timeout()
    if any(host == s or host.endswith("." + s) for s in _RU_SLOW_HOST_SUFFIXES):
        read = max(float(base.read or 45.0), float(settings.http_ru_read_timeout))
        connect = max(float(base.connect or 12.0), float(settings.http_connect_timeout))
        return httpx.Timeout(
            connect=connect,
            read=read,
            write=min(read, 30.0),
            pool=min(connect, 10.0),
        )
    return base


def get_client() -> httpx.AsyncClient:
    global _client
    if _client is None or _client.is_closed:
        kwargs: dict = {
            "headers": _default_headers(),
            "timeout": _build_timeout(),
            "follow_redirects": True,
            "verify": _ssl_verify(),
            "trust_env": True,
            "limits": httpx.Limits(
                max_connections=settings.http_max_connections,
                max_keepalive_connections=settings.http_max_keepalive,
            ),
        }
        proxy = _resolve_proxy()
        if proxy:
            kwargs["proxy"] = proxy
        _client = httpx.AsyncClient(**kwargs)
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


def _backoff_delay(attempt: int) -> float:
    """Exponential backoff with light jitter — helps geo-flaky RU endpoints."""
    base = min(12.0, 0.7 * (2 ** (attempt - 1)))
    return base + random.uniform(0.0, 0.45)


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
    timeout = _timeout_for_url(url)

    # Prefer Referer for AJAX/search paths on commercial ETPs
    req_headers = dict(headers or {})
    if "Referer" not in req_headers and "referer" not in req_headers:
        parsed = urlparse(url)
        if parsed.scheme and parsed.netloc:
            req_headers["Referer"] = f"{parsed.scheme}://{parsed.netloc}/"

    for attempt in range(1, attempts + 1):
        try:
            resp = await client.get(url, headers=req_headers, timeout=timeout)
            if resp.status_code in retry_statuses and attempt < attempts:
                last_resp = resp
                delay = _backoff_delay(attempt)
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
            await asyncio.sleep(_backoff_delay(attempt))

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
