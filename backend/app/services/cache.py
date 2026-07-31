from __future__ import annotations

import hashlib
import time
from threading import Lock
from typing import Any, Callable, TypeVar

T = TypeVar("T")

_lock = Lock()
_store: dict[str, tuple[float, Any]] = {}


def cache_get(key: str) -> Any | None:
    now = time.monotonic()
    with _lock:
        item = _store.get(key)
        if not item:
            return None
        expires, value = item
        if expires < now:
            _store.pop(key, None)
            return None
        return value


def cache_set(key: str, value: Any, ttl_seconds: float) -> None:
    with _lock:
        _store[key] = (time.monotonic() + ttl_seconds, value)
        if len(_store) > 1000:
            # Drop expired / oldest
            now = time.monotonic()
            expired = [k for k, (exp, _) in _store.items() if exp < now]
            for k in expired:
                _store.pop(k, None)
            if len(_store) > 1000:
                for k, _ in sorted(_store.items(), key=lambda x: x[1][0])[:200]:
                    _store.pop(k, None)


def cache_clear(prefix: str | None = None) -> None:
    with _lock:
        if prefix is None:
            _store.clear()
            return
        for k in [k for k in _store if k.startswith(prefix)]:
            _store.pop(k, None)


def make_key(namespace: str, raw: str) -> str:
    digest = hashlib.sha1(raw.encode("utf-8")).hexdigest()
    return f"{namespace}:{digest}"


def cached(namespace: str, key_raw: str, ttl: float, factory: Callable[[], T]) -> T:
    key = make_key(namespace, key_raw)
    hit = cache_get(key)
    if hit is not None:
        return hit
    value = factory()
    cache_set(key, value, ttl)
    return value
