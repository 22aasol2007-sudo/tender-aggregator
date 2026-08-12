"""OpenAI-compatible LLM research for supplier shortlist candidates (no prices)."""

from __future__ import annotations

import json
import logging
import re
from typing import Any

import httpx

from app.config import settings

log = logging.getLogger(__name__)


def _extract_json_array(text: str) -> list[dict[str, Any]]:
    text = (text or "").strip()
    if not text:
        return []
    # fenced ```json
    m = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
    if m:
        text = m.group(1).strip()
    try:
        data = json.loads(text)
        if isinstance(data, dict) and "suppliers" in data:
            data = data["suppliers"]
        if isinstance(data, list):
            return [x for x in data if isinstance(x, dict)]
    except json.JSONDecodeError:
        pass
    # try first [...] slice
    start, end = text.find("["), text.rfind("]")
    if start >= 0 and end > start:
        try:
            data = json.loads(text[start : end + 1])
            if isinstance(data, list):
                return [x for x in data if isinstance(x, dict)]
        except json.JSONDecodeError:
            return []
    return []


def research_suppliers_web(
    *,
    product: str,
    city: str,
    qty: float | None = None,
    unit: str | None = None,
    attrs: dict | None = None,
    niche_title: str = "",
    search_terms: list[str] | None = None,
) -> list[dict[str, Any]]:
    """Return candidate suppliers from LLM market knowledge. Never include prices."""
    api_key = (settings.openai_api_key or "").strip()
    if not api_key:
        return []

    base = (settings.openai_base_url or "https://api.openai.com/v1").rstrip("/")
    model = settings.openai_model or "gpt-4o-mini"
    timeout = float(getattr(settings, "shortlist_web_timeout_s", 55) or 55)

    attrs_s = json.dumps(attrs or {}, ensure_ascii=False)
    terms = ", ".join((search_terms or [])[:8])
    qty_s = f"{qty} {unit or ''}".strip() if qty is not None else "не указано"

    system = (
        "Ты — аналитик рынка B2B-поставок в России. "
        "Нужен shortlist реальных компаний-поставщиков/производителей. "
        "НЕ указывай цены, КП, прайсы или суммы. "
        "Верни ТОЛЬКО JSON-массив объектов."
    )
    user = f"""
Ниша: {niche_title or 'упаковка'}
Товар: {product}
Город/регион поставки: {city}
Количество: {qty_s}
Атрибуты SKU: {attrs_s}
Поисковые термины: {terms}

Найди 8–12 сильных кандидатов (производители предпочтительнее дилеров) для поставки в указанный регион.
Для каждого объекта поля:
- name (строка, юр. или бренд)
- inn (строка или null)
- role: "manufacturer" | "dealer" | "unknown"
- city, region (строки или null)
- website, email, phone (строки или null — только если уверены)
- confidence: число 0..1
- reasons: массив из 1–3 коротких фраз на русском (почему подходит), без цен

Только JSON-массив, без markdown.
""".strip()

    payload = {
        "model": model,
        "temperature": 0.2,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
    }

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    url = f"{base}/chat/completions"
    try:
        with httpx.Client(timeout=timeout) as client:
            resp = client.post(url, headers=headers, json=payload)
            resp.raise_for_status()
            body = resp.json()
    except Exception as exc:  # noqa: BLE001
        log.warning("web supplier research failed: %s", exc)
        raise

    content = ""
    try:
        content = body["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise RuntimeError(f"bad LLM response shape: {exc}") from exc

    rows = _extract_json_array(content)
    out: list[dict[str, Any]] = []
    for r in rows:
        name = str(r.get("name") or "").strip()
        if len(name) < 2:
            continue
        role = str(r.get("role") or "unknown").casefold()
        if role not in ("manufacturer", "dealer", "unknown"):
            role = "unknown"
        conf = r.get("confidence")
        try:
            conf_f = float(conf) if conf is not None else 0.5
        except (TypeError, ValueError):
            conf_f = 0.5
        reasons = r.get("reasons") if isinstance(r.get("reasons"), list) else []
        reasons = [str(x)[:160] for x in reasons if str(x).strip()][:3]
        # Strip any accidental price-looking fields
        out.append(
            {
                "name": name[:200],
                "inn": (str(r["inn"]).strip()[:16] if r.get("inn") else None),
                "role": role,
                "city": (str(r["city"]).strip()[:128] if r.get("city") else None),
                "region": (str(r["region"]).strip()[:128] if r.get("region") else None),
                "website": (str(r["website"]).strip()[:500] if r.get("website") else None),
                "email": (str(r["email"]).strip()[:255] if r.get("email") else None),
                "phone": (str(r["phone"]).strip()[:64] if r.get("phone") else None),
                "confidence": max(0.0, min(1.0, conf_f)),
                "reasons": reasons or ["Кандидат по исследованию рынка"],
            }
        )
    return out[:12]
