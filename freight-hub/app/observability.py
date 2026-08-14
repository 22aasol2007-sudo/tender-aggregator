"""Optional Sentry + structured log helpers."""

from __future__ import annotations

import logging
import os
from typing import Any

log = logging.getLogger("observability")
_sentry_inited = False


def init_sentry() -> bool:
    global _sentry_inited
    dsn = (os.getenv("SENTRY_DSN") or "").strip()
    if not dsn or _sentry_inited:
        return _sentry_inited
    try:
        import sentry_sdk
        from sentry_sdk.integrations.fastapi import FastApiIntegration

        sentry_sdk.init(
            dsn=dsn,
            traces_sample_rate=float(os.getenv("SENTRY_TRACES", "0.05") or 0.05),
            environment=os.getenv("SENTRY_ENV", "production"),
            integrations=[FastApiIntegration()],
        )
        _sentry_inited = True
        log.info("Sentry enabled")
    except Exception as exc:
        log.warning("Sentry init failed: %s", exc)
        _sentry_inited = False
    return _sentry_inited


def log_event(event: str, **fields: Any) -> None:
    parts = " ".join(f"{k}={v!r}" for k, v in fields.items() if v is not None)
    log.info("event=%s %s", event, parts)
