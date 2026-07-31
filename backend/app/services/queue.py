from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import TypeVar

import httpx

from app.config import settings

T = TypeVar("T")


async def with_retries(
    factory: Callable[[], Awaitable[T]],
    *,
    retries: int | None = None,
    base_delay: float = 0.8,
) -> T:
    attempts = retries if retries is not None else settings.http_retries
    last_exc: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            return await factory()
        except (httpx.HTTPError, TimeoutError, OSError) as exc:
            last_exc = exc
            if attempt >= attempts:
                break
            await asyncio.sleep(base_delay * attempt)
    assert last_exc is not None
    raise last_exc


class ScrapeQueue:
    """Simple in-process queue: one scrape at a time, retries per source handled by caller."""

    def __init__(self) -> None:
        self._lock = asyncio.Lock()

    async def run(self, coro_factory: Callable[[], Awaitable[T]]) -> T:
        async with self._lock:
            return await with_retries(coro_factory, retries=1)


scrape_queue = ScrapeQueue()
