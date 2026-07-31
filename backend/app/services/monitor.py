from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.config import settings
from app.models import SourceHealth
from app.services.health import ensure_source_rows, source_metrics
from app.services.telegram import send_telegram_message


CRITICAL_SOURCES = ("zakupki_44", "zakupki_223")


def monitor_snapshot(db: Session) -> dict:
    ensure_source_rows(db)
    metrics = source_metrics(db)
    now = datetime.now(timezone.utc)
    silence_minutes = settings.source_silence_minutes
    alerts: list[dict] = []

    for row in metrics:
        last_ok = row["last_ok_at"]
        silent = False
        silent_for = None
        if last_ok is None:
            silent = row["last_run_at"] is not None or row["last_status"] != "unknown"
            silent_for = None
        else:
            delta = now - (last_ok if last_ok.tzinfo else last_ok.replace(tzinfo=timezone.utc))
            silent_for = int(delta.total_seconds() // 60)
            silent = silent_for >= silence_minutes

        row["silent"] = silent
        row["silent_for_minutes"] = silent_for
        if silent and row["source"] in CRITICAL_SOURCES:
            alerts.append(
                {
                    "source": row["source"],
                    "message": f"Источник {row['display_name']} молчит ≥ {silence_minutes} мин",
                    "silent_for_minutes": silent_for,
                }
            )

    unhealthy = [m for m in metrics if m["last_status"] in {"fallback", "error"} or m["consecutive_failures"] >= 3]
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
