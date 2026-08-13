"""Extract ATI (and similar) load fields from a screenshot, then price the haul."""

from __future__ import annotations

import base64
import json
import logging
import re
from io import BytesIO
from typing import Any

import httpx

from app import config
from app.ingest import parse_price_rub
from app.parse import _canon_city, parse_load

log = logging.getLogger("screenshot_offer")

MAX_IMAGE_BYTES = 8 * 1024 * 1024
VISION_PROMPT = """Ты разбираешь скриншот объявления с биржи грузов ATI.SU (или похожей).
Верни ТОЛЬКО JSON без markdown:
{
  "from_city": "город погрузки или null",
  "to_city": "город выгрузки или null",
  "price_rub": число ставки в рублях целиком или null,
  "price_per_km": число ₽/км или null,
  "tonnage": тонны числом или null,
  "body": "reefer|isotherm|tent|board|box|null",
  "route_km": километраж числом или null,
  "raw_text": "краткий текст с экрана"
}
Города — одним словом/названием на русском (Москва, Тула, Казань…).
Если ставка «от 45 000» — бери 45000. Если только ₽/км — заполни price_per_km.
"""


def vision_configured() -> dict[str, bool]:
    return {
        "gemini": bool((getattr(config, "GEMINI_API_KEY", "") or "").strip()),
        "openai": bool((getattr(config, "OPENAI_API_KEY", "") or "").strip()),
        "ocr": _ocr_available(),
    }


def _ocr_available() -> bool:
    try:
        import pytesseract  # noqa: F401
        from PIL import Image  # noqa: F401

        return True
    except Exception:
        return False


def _norm_city(val: Any) -> str | None:
    if val is None:
        return None
    s = str(val).strip()
    if not s or s.lower() in {"null", "none", "-"}:
        return None
    # Drop region tails: "Тула, Тульская обл."
    s = re.split(r"[,;(]", s, maxsplit=1)[0].strip()
    return _canon_city(s) or s.lower() or None


def _norm_body(val: Any) -> str | None:
    if val is None:
        return None
    s = str(val).strip().lower().replace("ё", "е")
    if not s or s in {"null", "none"}:
        return None
    if "реф" in s or "refriger" in s:
        return "reefer"
    if "изотерм" in s or "isotherm" in s:
        return "isotherm"
    if "тент" in s or "curtain" in s or "tent" in s:
        return "tent"
    if "борт" in s or "board" in s:
        return "board"
    if "фургон" in s or "box" in s or "цельнометалл" in s:
        return "box"
    if s in {"reefer", "isotherm", "tent", "board", "box"}:
        return s
    return None


def fields_from_text(text: str) -> dict[str, Any]:
    """Heuristic + freight_core parse for OCR / pasted ATI text."""
    raw = (text or "").strip()
    parsed = parse_load(raw) if raw else None
    price = None
    ppk = None
    # ATI often shows "45 000 ₽" or "120 ₽/км"
    for m in re.finditer(
        r"(\d[\d\s]{2,8})\s*(?:₽|руб|р\.)(?:\s*/\s*км|\s*за\s*км)?",
        raw.lower().replace("ё", "е"),
        flags=re.I,
    ):
        chunk = m.group(0)
        if "/км" in chunk or "за км" in chunk:
            try:
                ppk = float(re.sub(r"[^\d.,]", "", m.group(1)).replace(",", "."))
            except ValueError:
                pass
        else:
            price = parse_price_rub(m.group(1) + " руб") or price

    tonnage = parsed.tonnage if parsed else None
    if tonnage is None:
        m = re.search(r"(\d+[.,]?\d*)\s*(?:т\b|тонн)", raw.lower())
        if m:
            try:
                tonnage = float(m.group(1).replace(",", "."))
            except ValueError:
                pass

    route_km = None
    m = re.search(r"(\d{2,5})\s*км", raw.lower())
    if m:
        try:
            route_km = float(m.group(1))
        except ValueError:
            pass

    from_city = _norm_city(parsed.from_city if parsed else None)
    to_city = _norm_city(parsed.to_city if parsed else None)
    # ATI arrow patterns — prefer over noisy parse_load hits (e.g. "ATI.SU")
    m = re.search(
        r"([А-Яа-яЁёA-Za-z\-]{3,30})\s*(?:→|->|—|–)\s*([А-Яа-яЁёA-Za-z\-]{3,30})",
        raw,
    )
    if not m:
        m = re.search(
            r"([А-Яа-яЁё]{3,30})\s+-\s+([А-Яа-яЁё]{3,30})",
            raw,
        )
    if m:
        arrow_from = _norm_city(m.group(1))
        arrow_to = _norm_city(m.group(2))
        if arrow_from and arrow_to:
            from_city, to_city = arrow_from, arrow_to

    body = _norm_body(parsed.body if parsed else None) or _norm_body(raw)
    if parsed and parsed.price and price is None:
        price = parse_price_rub(parsed.price)

    return {
        "from_city": from_city,
        "to_city": to_city,
        "price_rub": float(price) if price is not None else None,
        "price_per_km": float(ppk) if ppk is not None else None,
        "tonnage": float(tonnage) if tonnage is not None else None,
        "body": body,
        "route_km": float(route_km) if route_km is not None else None,
        "raw_text": raw[:2000],
    }


def merge_fields(*parts: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {
        "from_city": None,
        "to_city": None,
        "price_rub": None,
        "price_per_km": None,
        "tonnage": None,
        "body": None,
        "route_km": None,
        "raw_text": "",
    }
    texts: list[str] = []
    for p in parts:
        if not p:
            continue
        for k in out:
            if k == "raw_text":
                continue
            if out[k] is None and p.get(k) not in (None, "", "null"):
                out[k] = p[k]
        if p.get("raw_text"):
            texts.append(str(p["raw_text"]))
    out["from_city"] = _norm_city(out.get("from_city"))
    out["to_city"] = _norm_city(out.get("to_city"))
    out["body"] = _norm_body(out.get("body"))
    out["raw_text"] = "\n".join(texts)[:2000]
    return out


def ocr_image(image_bytes: bytes) -> str:
    from PIL import Image
    import pytesseract

    img = Image.open(BytesIO(image_bytes))
    if img.mode not in {"RGB", "L"}:
        img = img.convert("RGB")
    # Upscale small screenshots for better OCR
    w, h = img.size
    if max(w, h) < 1200:
        img = img.resize((w * 2, h * 2))
    try:
        text = pytesseract.image_to_string(img, lang="rus+eng")
    except Exception:
        text = pytesseract.image_to_string(img)
    return (text or "").strip()


def _parse_json_loose(text: str) -> dict[str, Any]:
    raw = (text or "").strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```(?:json)?\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw)
    try:
        data = json.loads(raw)
        return data if isinstance(data, dict) else {}
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", raw, flags=re.S)
        if not m:
            return {}
        try:
            data = json.loads(m.group(0))
            return data if isinstance(data, dict) else {}
        except json.JSONDecodeError:
            return {}


async def vision_gemini(image_bytes: bytes, mime: str) -> dict[str, Any]:
    key = (getattr(config, "GEMINI_API_KEY", "") or "").strip()
    if not key:
        return {}
    model = (getattr(config, "GEMINI_VISION_MODEL", "") or "gemini-2.0-flash").strip()
    b64 = base64.b64encode(image_bytes).decode("ascii")
    url = (
        f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
        f"?key={key}"
    )
    body = {
        "contents": [
            {
                "parts": [
                    {"text": VISION_PROMPT},
                    {"inline_data": {"mime_type": mime, "data": b64}},
                ]
            }
        ],
        "generationConfig": {"temperature": 0.1, "maxOutputTokens": 800},
    }
    async with httpx.AsyncClient(timeout=45.0) as client:
        r = await client.post(url, json=body)
        if r.status_code >= 400:
            log.warning("gemini vision %s: %s", r.status_code, r.text[:300])
            return {}
        data = r.json()
    try:
        text = data["candidates"][0]["content"]["parts"][0]["text"]
    except (KeyError, IndexError, TypeError):
        return {}
    parsed = _parse_json_loose(text)
    return {
        "from_city": _norm_city(parsed.get("from_city")),
        "to_city": _norm_city(parsed.get("to_city")),
        "price_rub": _num(parsed.get("price_rub")),
        "price_per_km": _num(parsed.get("price_per_km")),
        "tonnage": _num(parsed.get("tonnage")),
        "body": _norm_body(parsed.get("body")),
        "route_km": _num(parsed.get("route_km")),
        "raw_text": str(parsed.get("raw_text") or text)[:2000],
    }


async def vision_openai(image_bytes: bytes, mime: str) -> dict[str, Any]:
    key = (getattr(config, "OPENAI_API_KEY", "") or "").strip()
    if not key:
        return {}
    base = (getattr(config, "OPENAI_BASE_URL", "") or "https://api.openai.com/v1").rstrip("/")
    model = (getattr(config, "OPENAI_VISION_MODEL", "") or "gpt-4o-mini").strip()
    b64 = base64.b64encode(image_bytes).decode("ascii")
    data_url = f"data:{mime};base64,{b64}"
    payload = {
        "model": model,
        "temperature": 0.1,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": VISION_PROMPT},
                    {"type": "image_url", "image_url": {"url": data_url}},
                ],
            }
        ],
    }
    headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
    async with httpx.AsyncClient(timeout=45.0) as client:
        r = await client.post(f"{base}/chat/completions", headers=headers, json=payload)
        if r.status_code >= 400:
            log.warning("openai vision %s: %s", r.status_code, r.text[:300])
            return {}
        data = r.json()
    try:
        text = data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError):
        return {}
    parsed = _parse_json_loose(text if isinstance(text, str) else str(text))
    return {
        "from_city": _norm_city(parsed.get("from_city")),
        "to_city": _norm_city(parsed.get("to_city")),
        "price_rub": _num(parsed.get("price_rub")),
        "price_per_km": _num(parsed.get("price_per_km")),
        "tonnage": _num(parsed.get("tonnage")),
        "body": _norm_body(parsed.get("body")),
        "route_km": _num(parsed.get("route_km")),
        "raw_text": str(parsed.get("raw_text") or text)[:2000],
    }


def _num(val: Any) -> float | None:
    if val is None or val == "" or val == "null":
        return None
    try:
        return float(str(val).replace(" ", "").replace(",", "."))
    except (TypeError, ValueError):
        return None


def sniff_mime(image_bytes: bytes, filename: str | None = None) -> str:
    name = (filename or "").lower()
    if name.endswith(".png"):
        return "image/png"
    if name.endswith(".webp"):
        return "image/webp"
    if name.endswith(".gif"):
        return "image/gif"
    if image_bytes[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if image_bytes[:2] == b"\xff\xd8":
        return "image/jpeg"
    if image_bytes[:4] == b"RIFF" and image_bytes[8:12] == b"WEBP":
        return "image/webp"
    return "image/jpeg"


async def extract_from_screenshot(
    image_bytes: bytes,
    *,
    filename: str | None = None,
) -> dict[str, Any]:
    if not image_bytes:
        return {"ok": False, "error": "Пустой файл", "fields": {}, "method": None}
    if len(image_bytes) > MAX_IMAGE_BYTES:
        return {"ok": False, "error": "Файл больше 8 МБ", "fields": {}, "method": None}

    mime = sniff_mime(image_bytes, filename)
    methods: list[str] = []
    vision_fields: dict[str, Any] = {}
    ocr_fields: dict[str, Any] = {}

    # Prefer vision when configured
    if (getattr(config, "GEMINI_API_KEY", "") or "").strip():
        vision_fields = await vision_gemini(image_bytes, mime)
        if vision_fields.get("from_city") or vision_fields.get("to_city"):
            methods.append("gemini")
    if not vision_fields.get("from_city") and not vision_fields.get("to_city"):
        if (getattr(config, "OPENAI_API_KEY", "") or "").strip():
            vision_fields = await vision_openai(image_bytes, mime)
            if vision_fields.get("from_city") or vision_fields.get("to_city"):
                methods.append("openai")

    ocr_text = ""
    if _ocr_available():
        try:
            ocr_text = ocr_image(image_bytes)
            if ocr_text:
                ocr_fields = fields_from_text(ocr_text)
                methods.append("ocr")
        except Exception as exc:
            log.warning("ocr failed: %s", exc)

    fields = merge_fields(vision_fields, ocr_fields)
    if not fields.get("raw_text") and ocr_text:
        fields["raw_text"] = ocr_text[:2000]

    if not fields.get("from_city") and not fields.get("to_city"):
        cfg = vision_configured()
        hint = (
            "Не удалось прочитать маршрут со скрина. "
            "Проверьте качество фото"
            + (
                ""
                if cfg["gemini"] or cfg["openai"]
                else " или задайте GEMINI_API_KEY для точного разбора ATI"
            )
            + "."
        )
        return {"ok": False, "error": hint, "fields": fields, "method": "+".join(methods) or None}

    return {
        "ok": True,
        "fields": fields,
        "method": "+".join(methods) or "unknown",
        "vision_ready": vision_configured(),
    }


def resolve_analyze_targets(
    fields: dict[str, Any],
    *,
    base: str,
) -> dict[str, Any]:
    """
    Decide destination for backhaul math and listed offer from ATI card.

    Carrier base is usually Москва. Destination = far end of the trip
    (city that is not the base). Listed ATI rate becomes offer_rub.
    """
    base_n = (base or "москва").strip().lower().replace("ё", "е") or "москва"
    frm = (fields.get("from_city") or "").strip().lower().replace("ё", "е")
    to = (fields.get("to_city") or "").strip().lower().replace("ё", "е")

    def near_base(city: str) -> bool:
        if not city:
            return False
        return base_n in city or city in base_n or city.startswith(base_n[:4])

    if near_base(frm) and to:
        destination = to
        direction = "outbound"  # base → dest
    elif near_base(to) and frm:
        destination = frm
        direction = "inbound"  # dest → base (this load IS the backhaul)
    elif to:
        destination = to
        direction = "outbound"
    else:
        destination = frm
        direction = "unknown"

    offer = fields.get("price_rub")
    if offer is None and fields.get("price_per_km") and fields.get("route_km"):
        try:
            offer = float(fields["price_per_km"]) * float(fields["route_km"])
        except (TypeError, ValueError):
            offer = None

    return {
        "base": base_n,
        "destination": destination,
        "direction": direction,
        "from_city": frm or None,
        "to_city": to or None,
        "offer_rub": float(offer) if offer is not None else None,
        "tonnage": fields.get("tonnage"),
        "body": fields.get("body"),
        "listed_route_km": fields.get("route_km"),
        "listed_ppk": fields.get("price_per_km"),
    }
