"""Hourly ingest counters — why the feed is quiet or noisy."""

from __future__ import annotations

import time
from collections import defaultdict
from typing import Any

# bucket_hour -> reason -> count
_BUCKETS: dict[int, dict[str, int]] = defaultdict(lambda: defaultdict(int))
_SEEN_SOURCES: dict[int, dict[str, int]] = defaultdict(lambda: defaultdict(int))


def _hour(ts: float | None = None) -> int:
    return int((ts or time.time()) // 3600)


def record(reason: str, *, source: str | None = None, n: int = 1) -> None:
    h = _hour()
    key = (reason or "unknown").strip() or "unknown"
    _BUCKETS[h][key] += int(n)
    if source:
        _SEEN_SOURCES[h][str(source)] += int(n)
    # keep ~48h
    cutoff = h - 48
    for old in list(_BUCKETS.keys()):
        if old < cutoff:
            _BUCKETS.pop(old, None)
            _SEEN_SOURCES.pop(old, None)


def snapshot(*, hours: int = 1) -> dict[str, Any]:
    h_now = _hour()
    merged: dict[str, int] = defaultdict(int)
    by_source: dict[str, int] = defaultdict(int)
    for age in range(max(1, hours)):
        h = h_now - age
        for k, v in _BUCKETS.get(h, {}).items():
            merged[k] += v
        for k, v in _SEEN_SOURCES.get(h, {}).items():
            by_source[k] += v
    added = int(merged.get("added", 0))
    return {
        "window_hours": hours,
        "added": added,
        "updated": int(merged.get("updated", 0)),
        "skipped_geo": int(merged.get("skipped_geo", 0)),
        "skipped_tonnage": int(merged.get("skipped_tonnage", 0)),
        "skipped_dup": int(merged.get("skipped_dup", 0)),
        "skipped_age": int(merged.get("skipped_age", 0)),
        "skipped_other": int(merged.get("skipped_other", 0)),
        "live_seen": int(merged.get("live_seen", 0)),
        "by_reason": dict(sorted(merged.items(), key=lambda x: -x[1])),
        "by_source": dict(sorted(by_source.items(), key=lambda x: -x[1])),
    }
