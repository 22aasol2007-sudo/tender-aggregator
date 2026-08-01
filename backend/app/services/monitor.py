from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.config import settings
from app.models import SourceHealth
from app.parsers import get_parsers
from app.services.health import ensure_source_rows, source_metrics
from app.services.telegram import send_telegram_message


CRITICAL_SOURCES = ("zakupki_44", "zakupki_223")
# Statuses that mean "configured gap / intentional skip" — never «молчит»
_NON_SILENT_STATUSES = frozenset({"needs_api", "skipped", "unknown"})


def _parser_flags(source_id: str) -> dict:
    parser = get_parsers().get(source_id)
    requires_api = bool(parser and getattr(parser, "requires_api", False))
    api_ready = bool(parser and getattr(parser, "api_ready", False))
    public_listing = bool(parser is None or getattr(parser, "public_listing", True))
    # Scrape-capable: we expect HTTP listing/API without paid credentials
    scrape_capable = (not requires_api or api_ready) and public_listing
    return {
        "requires_api": requires_api,
        "api_ready": api_ready,
        "public_listing": public_listing,
        "scrape_capable": scrape_capable,
    }


def monitor_snapshot(db: Session) -> dict:
    ensure_source_rows(db)
    metrics = source_metrics(db)
    now = datetime.now(timezone.utc)
    silence_minutes = settings.source_silence_minutes
    alerts: list[dict] = []

    for row in metrics:
        flags = _parser_flags(row["source"])
        row.update(flags)

        last_ok = row["last_ok_at"]
        status = row["last_status"] or "unknown"
        silent = False
        silent_for = None

        # needs_api / SPA unavailable / fail-fast skip → never «молчит»
        if status in _NON_SILENT_STATUSES or not flags["scrape_capable"]:
            silent = False
            silent_for = None
        elif last_ok is None:
            # Never succeeded: only alarm critical EIS (geo/proxy gap), not every empty ETP
            silent = row["source"] in CRITICAL_SOURCES and row["last_run_at"] is not None
            silent_for = None
        else:
            delta = now - (last_ok if last_ok.tzinfo else last_ok.replace(tzinfo=timezone.utc))
            silent_for = int(delta.total_seconds() // 60)
            silent = silent_for >= silence_minutes

        row["silent"] = silent
        row["silent_for_minutes"] = silent_for
        if silent and row["source"] in CRITICAL_SOURCES:
            msg = f"Источник {row['display_name']} молчит ≥ {silence_minutes} мин"
            err = (row.get("last_error") or "").lower()
            proxy_on = bool(
                (settings.scrape_proxy_url or "").strip()
                or (settings.http_proxy or "").strip()
                or (settings.https_proxy or "").strip()
            )
            if proxy_on and (
                "geo" in err
                or "captcha" in err
                or "без item" in err
                or "пуст" in err
                or row.get("last_status") == "empty"
            ):
                msg += (
                    ". Прокси есть, но ЕИС пуст — нужен ISP/residential RU-прокси "
                    "(datacenter часто режется captcha/geo)."
                )
            alerts.append(
                {
                    "source": row["source"],
                    "message": msg,
                    "silent_for_minutes": silent_for,
                }
            )

    unhealthy = [
        m
        for m in metrics
        if m.get("scrape_capable", True)
        and (
            m["last_status"] in {"fallback", "error"}
            or (m["consecutive_failures"] >= 3 and m["last_status"] not in {"needs_api", "skipped"})
        )
    ]
    return {
        "checked_at": now.isoformat(),
        "silence_minutes": silence_minutes,
        "sources": metrics,
        "unhealthy_count": len(unhealthy),
        "alerts": alerts,
    }


async def run_monitor_and_alert(db: Session) -> dict:
    snap = monitor_snapshot(db)
    now = datetime.now(timezone.utc)
    chat_id = settings.monitor_telegram_chat_id
    if not chat_id or not settings.telegram_bot_token:
        return snap

    for alert in snap["alerts"]:
        source = alert["source"]
        row = db.query(SourceHealth).filter(SourceHealth.source == source).one_or_none()
        if not row:
            continue
        # Don't spam more than once per silence window
        if row.silence_alerted_at:
            alerted = row.silence_alerted_at
            if alerted.tzinfo is None:
                alerted = alerted.replace(tzinfo=timezone.utc)
            if now - alerted < timedelta(minutes=settings.source_silence_minutes):
                continue
        ok = await send_telegram_message(
            chat_id,
            f"⚠️ Мониторинг Tender Aggregator\n{alert['message']}",
        )
        if ok:
            row.silence_alerted_at = now
            db.commit()
    return snap
