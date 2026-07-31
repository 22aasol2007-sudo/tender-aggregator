from __future__ import annotations

import hashlib
import re
import unicodedata

STATUS_ACCEPTING = "accepting"
STATUS_COMPLETED = "completed"
STATUS_CANCELLED = "cancelled"
STATUS_UNKNOWN = "unknown"

STATUS_LABELS = {
    STATUS_ACCEPTING: "Приём заявок",
    STATUS_COMPLETED: "Завершён",
    STATUS_CANCELLED: "Отменён",
    STATUS_UNKNOWN: "Неизвестно",
}

REGION_ALIASES = {
    "г. москва": "Москва",
    "город москва": "Москва",
    "москва г": "Москва",
    "г москва": "Москва",
    "г. санкт-петербург": "Санкт-Петербург",
    "город санкт-петербург": "Санкт-Петербург",
    "санкт петербург": "Санкт-Петербург",
    "спб": "Санкт-Петербург",
    "ленинградская обл": "Ленинградская область",
    "ленинградская область": "Ленинградская область",
    "московская обл": "Московская область",
    "московская область": "Московская область",
    "респ. татарстан": "Республика Татарстан",
    "республика татарстан": "Республика Татарстан",
    "свердловская обл": "Свердловская область",
    "новосибирская обл": "Новосибирская область",
    "краснодарский край": "Краснодарский край",
}

ACCEPTING_MARKERS = (
    "подача",
    "прием",
    "приём",
    "размещен",
    "размещён",
    "прием заявок",
    "приём заявок",
    "подача заявок",
    "active",
    "открыт",
)
COMPLETED_MARKERS = (
    "завершен",
    "завершён",
    "исполнен",
    "контракт заключен",
    "контракт заключён",
    "определен поставщик",
    "определён поставщик",
    "архив",
    "closed",
)
CANCELLED_MARKERS = ("отменен", "отменён", "аннулирован", "cancelled")

OKPD_RE = re.compile(r"\b(\d{2}(?:\.\d{1,3}){0,4})\b")
WHITESPACE_RE = re.compile(r"\s+")


def _collapse(text: str) -> str:
    return WHITESPACE_RE.sub(" ", text).strip()


def normalize_text(value: str | None) -> str | None:
    if not value:
        return None
    text = unicodedata.normalize("NFKC", value)
    text = text.replace("\xa0", " ")
    return _collapse(text) or None


def normalize_region(value: str | None) -> str | None:
    text = normalize_text(value)
    if not text:
        return None
    key = text.lower().replace(".", "").replace("  ", " ").strip()
    key = key.replace("область", "обл").replace("республика", "респ")
    return REGION_ALIASES.get(key, text)


def normalize_price(value: float | None) -> float | None:
    if value is None:
        return None
    try:
        price = float(value)
    except (TypeError, ValueError):
        return None
    if price <= 0:
        return None
    return round(price, 2)


def normalize_status(raw: str | None, deadline_passed: bool = False) -> tuple[str, str]:
    text = (raw or "").lower()
    if any(m in text for m in CANCELLED_MARKERS):
        return STATUS_CANCELLED, STATUS_LABELS[STATUS_CANCELLED]
    if any(m in text for m in COMPLETED_MARKERS) or deadline_passed:
        return STATUS_COMPLETED, STATUS_LABELS[STATUS_COMPLETED]
    if any(m in text for m in ACCEPTING_MARKERS) or not text:
        if deadline_passed:
            return STATUS_COMPLETED, STATUS_LABELS[STATUS_COMPLETED]
        return STATUS_ACCEPTING, STATUS_LABELS[STATUS_ACCEPTING]
    if deadline_passed:
        return STATUS_COMPLETED, STATUS_LABELS[STATUS_COMPLETED]
    return STATUS_UNKNOWN, normalize_text(raw) or STATUS_LABELS[STATUS_UNKNOWN]


def extract_okpd2(text: str | None) -> str | None:
    if not text:
        return None
    match = OKPD_RE.search(text)
    return match.group(1) if match else None


def make_fingerprint(
    title: str,
    customer: str | None,
    price: float | None,
    region: str | None = None,
) -> str:
    base = "|".join(
        [
            (normalize_text(title) or "").lower(),
            (normalize_text(customer) or "").lower(),
            f"{price:.2f}" if price is not None else "",
            (normalize_region(region) or "").lower(),
        ]
    )
    return hashlib.sha1(base.encode("utf-8")).hexdigest()
