"""Extract freight-board load fields from a screenshot, then price the haul."""

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
VISION_PROMPT = """Ты разбираешь скриншот объявления о ГРУЗЕ с любой российской биржи/агрегатора
(ATI.SU, Перевозка24, Везёт Всем, CargoCash, PapaCargo, Roolz, Автодиспетчер, Loginet,
Cargomart, Svezem, Monopoly, Telegram/MAX и т.п.) или мобильного приложения.

Игнорируй рекламу, меню, кнопки «войти»/«показать контакты», иконки.
Возьми данные ИМЕННО выбранной карточки/объявления.

Верни ТОЛЬКО JSON без markdown:
{
  "board": "ati|perevozka24|vezetvsem|cargocash|papacargo|roolz|avtodispetcher|cargomart|svezem|monopoly|telegram|max|other|null",
  "from_city": "населённый пункт погрузки или null",
  "to_city": "населённый пункт выгрузки или null",
  "price_rub": число ставки в рублях целиком или null,
  "price_per_km": число ₽/км или null,
  "tonnage": тонны числом или null,
  "body": "reefer|isotherm|tent|board|box|null",
  "route_km": километраж плеча числом или null,
  "raw_text": "краткий текст с экрана"
}

Правила:
- Города — коротко по-русски. Из ATI бери пункты в колонке «Маршрут» (напр. Радумля, Петро-Славянка), НЕ область и НЕ подписи «загр/выгр/погр/разгр».
- НЕ путай номер заявки (#NKB…, #ATI…, NKB21947) со ставкой. Если ставки/цены на скрине нет — price_rub=null.
- Километраж маршрута (зелёный/основной км плеча) → route_km; не бери «км от Москва» как длину рейса, если есть явный км направления.
- Ставка «от 45 000» / «45000 руб» → price_rub=45000. Только «120 ₽/км» → price_per_km=120.
- Реф/рефрижератор → body=reefer; тент → tent; изотерм → isotherm; борт → board; фургон → box.
"""


_JUNK_CITY_TOKENS = {
    "загр",
    "выгр",
    "погр",
    "разгр",
    "задн",
    "задняя",
    "боков",
    "боковая",
    "верхн",
    "отд",
    "машина",
    "медкнижка",
    "палеты",
    "палет",
    "готов",
    "готова",
    "круглосуточно",
    "направл",
    "транспорт",
    "маршрут",
    "контакты",
    "показать",
    "rus",
    "nkb",
}


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
    # Drop region tails / type suffixes: "Радумля д.", "Тула, Тульская обл."
    s = re.split(r"[,;(]", s, maxsplit=1)[0].strip()
    s = re.sub(r"\s+[дпсху]\.\s*$", "", s, flags=re.I).strip()
    low = s.lower().replace("ё", "е")
    if low in _JUNK_CITY_TOKENS or any(low.startswith(j) for j in _JUNK_CITY_TOKENS if len(j) >= 4):
        return None
    if low in {"загр", "выгр", "погр", "разгр"}:
        return None
    return _canon_city(s) or (low if len(low) >= 3 else None)


def _sane_price_rub(price: float | None, *, raw: str = "", route_km: float | None = None) -> float | None:
    """Drop order ids / distances mistaken for client rate."""
    if price is None:
        return None
    try:
        p = float(price)
    except (TypeError, ValueError):
        return None
    if p < 3000 or p > 15_000_000:
        return None
    raw_l = (raw or "").lower().replace("ё", "е")
    # #NKB21947 / NKB21947 style refs
    dig = str(int(p)) if p == int(p) else str(p)
    if re.search(rf"(?:#?\s*nkb|#\s*[a-z]{{2,10}})\s*{re.escape(dig)}", raw_l):
        return None
    if re.search(rf"#\s*{re.escape(dig)}\b", raw_l):
        return None
    # Bare distance numbers often 3–4 digits + км
    if route_km and abs(p - float(route_km)) < 1:
        return None
    return p


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
    """Heuristic + freight_core parse for OCR / pasted board text."""
    raw = (text or "").strip()
    parsed = parse_load(raw) if raw else None
    price = None
    ppk = None
    raw_l = raw.lower().replace("ё", "е")
    # Prefer explicit rate markers; skip #NKB / order ids
    for m in re.finditer(
        r"(?:ставк[аие]\s*[:=]?\s*|цена\s*[:=]?\s*|оплат[аие]\s*[:=]?\s*)?"
        r"(\d[\d\s]{2,8})\s*(?:₽|руб\.?|р\.|тр\b|тыс)?"
        r"(?:\s*/\s*км|\s*за\s*км)?",
        raw_l,
        flags=re.I,
    ):
        chunk = m.group(0)
        num = m.group(1)
        prefix = raw_l[max(0, m.start() - 10) : m.start()]
        if "#" in prefix or "nkb" in prefix:
            continue
        if re.search(r"[a-zа-я]{2,}\s*$", prefix) and not re.search(
            r"(?:ставк|цена|оплат|руб|₽)\s*$", prefix
        ):
            # e.g. NKB21947 or mid-word digits without currency
            if "₽" not in chunk and "руб" not in chunk and "ставк" not in chunk and "тыс" not in chunk and "тр" not in chunk:
                continue
        if "/км" in chunk or "за км" in chunk:
            try:
                ppk = float(re.sub(r"[^\d.,]", "", num).replace(",", "."))
            except ValueError:
                pass
        else:
            if "₽" in chunk or "руб" in chunk or "ставк" in chunk or "тыс" in chunk or "тр" in chunk or "цена" in chunk:
                price = parse_price_rub(num + (" тыс руб" if "тыс" in chunk or "тр" in chunk else " руб")) or price

    tonnage = parsed.tonnage if parsed else None
    if tonnage is None:
        m = re.search(r"(\d+[.,]?\d*)\s*(?:т\b|тонн)", raw_l)
        if m:
            try:
                tonnage = float(m.group(1).replace(",", "."))
            except ValueError:
                pass
        # ATI "20 / 82" weight/volume
        m = re.search(r"\b(\d{1,2})\s*/\s*\d{2,3}\b", raw_l)
        if m and tonnage is None:
            try:
                tonnage = float(m.group(1))
            except ValueError:
                pass

    route_km = None
    # Prefer explicit direction km; avoid "51 км от Москва"
    for m in re.finditer(r"(\d{2,5})\s*км(?!\s*от)", raw_l):
        try:
            cand = float(m.group(1))
        except ValueError:
            continue
        if 30 <= cand <= 8000:
            route_km = cand
            break

    from_city = _norm_city(parsed.from_city if parsed else None)
    to_city = _norm_city(parsed.to_city if parsed else None)
    # Route arrows used across ATI / P24 / VezetVsem / TG
    m = re.search(
        r"([А-Яа-яЁёA-Za-z\-]{3,30})\s*(?:→|->|—|–|➜|⇒)\s*([А-Яа-яЁёA-Za-z\-]{3,30})",
        raw,
    )
    if not m:
        m = re.search(
            r"([А-Яа-яЁё]{3,30})\s+-\s+([А-Яа-яЁё]{3,30})",
            raw,
        )
    if not m:
        m = re.search(
            r"(?:откуда|погрузк[аи]|from)\s*[:\-]?\s*([А-Яа-яЁёA-Za-z\-\s]{3,40})"
            r".{0,40}?"
            r"(?:куда|выгрузк[аи]|to)\s*[:\-]?\s*([А-Яа-яЁёA-Za-z\-\s]{3,40})",
            raw,
            flags=re.I | re.S,
        )
    if m:
        arrow_from = _norm_city(m.group(1))
        arrow_to = _norm_city(m.group(2))
        if arrow_from and arrow_to:
            from_city, to_city = arrow_from, arrow_to

    # ATI-like: "Радумля д." ... later "Петро-Славянка п."
    if not from_city or not to_city:
        places = re.findall(
            r"\b([А-ЯЁ][а-яё]{2,}(?:-[А-ЯЁа-яё]+)?)\s*[дпсху]\.",
            raw,
        )
        cleaned = [_norm_city(p) for p in places]
        cleaned = [c for c in cleaned if c]
        if len(cleaned) >= 2:
            from_city = from_city or cleaned[0]
            to_city = to_city or cleaned[-1]

    body = _norm_body(parsed.body if parsed else None) or _norm_body(raw)
    if parsed and parsed.price and price is None:
        price = parse_price_rub(parsed.price)

    board = _detect_board(raw)
    price = _sane_price_rub(float(price) if price is not None else None, raw=raw, route_km=route_km)

    return {
        "board": board,
        "from_city": from_city,
        "to_city": to_city,
        "price_rub": float(price) if price is not None else None,
        "price_per_km": float(ppk) if ppk is not None else None,
        "tonnage": float(tonnage) if tonnage is not None else None,
        "body": body,
        "route_km": float(route_km) if route_km is not None else None,
        "raw_text": raw[:2000],
    }


def _detect_board(text: str) -> str | None:
    low = (text or "").lower().replace("ё", "е")
    rules = [
        ("ati", ("ati.su", "ati su", "loads.ati", "ати")),
        ("perevozka24", ("perevozka24", "перевозка 24", "перевозка24")),
        ("vezetvsem", ("vezetvsem", "везет всем", "везёт всем")),
        ("cargocash", ("cargocash", "каргокэш", "карго кеш")),
        ("papacargo", ("papacargo", "папакарго", "папа карго")),
        ("roolz", ("roolz", "рулз")),
        ("avtodispetcher", ("avtodispetcher", "автодиспетчер")),
        ("cargomart", ("cargomart", "каргомарт")),
        ("svezem", ("svezem", "свезем")),
        ("monopoly", ("monopoly", "монополи")),
        ("telegram", ("telegram", "t.me", "телеграм")),
        ("max", ("max.ru", "макс мессенджер")),
    ]
    for name, keys in rules:
        if any(k in low for k in keys):
            return name
    return None


def merge_fields(*parts: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {
        "board": None,
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
    if not out.get("board"):
        out["board"] = _detect_board(out.get("raw_text") or "\n".join(texts))
    out["raw_text"] = "\n".join(texts)[:2000]
    out["price_rub"] = _sane_price_rub(
        float(out["price_rub"]) if out.get("price_rub") is not None else None,
        raw=out["raw_text"],
        route_km=float(out["route_km"]) if out.get("route_km") is not None else None,
    )
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
    model = (getattr(config, "GEMINI_VISION_MODEL", "") or "gemini-flash-latest").strip()
    payload_bytes, payload_mime = _prepare_vision_image(image_bytes, mime)
    b64 = base64.b64encode(payload_bytes).decode("ascii")
    url = (
        f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
        f"?key={key}"
    )
    body = {
        "contents": [
            {
                "parts": [
                    {"text": VISION_PROMPT},
                    {"inline_data": {"mime_type": payload_mime, "data": b64}},
                ]
            }
        ],
        "generationConfig": {"temperature": 0.1, "maxOutputTokens": 800},
    }
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(90.0, connect=15.0)) as client:
            r = await client.post(url, json=body)
            if r.status_code >= 400:
                log.warning("gemini vision %s: %s", r.status_code, r.text[:300])
                return {}
            data = r.json()
    except httpx.TimeoutException as exc:
        log.warning("gemini vision timeout: %s", exc)
        return {}
    except Exception as exc:
        log.warning("gemini vision failed: %s", exc)
        return {}
    try:
        text = data["candidates"][0]["content"]["parts"][0]["text"]
    except (KeyError, IndexError, TypeError):
        return {}
    parsed = _parse_json_loose(text)
    route_km = _num(parsed.get("route_km"))
    price = _sane_price_rub(_num(parsed.get("price_rub")), raw=text, route_km=route_km)
    return {
        "board": parsed.get("board") or _detect_board(str(parsed.get("raw_text") or text)),
        "from_city": _norm_city(parsed.get("from_city")),
        "to_city": _norm_city(parsed.get("to_city")),
        "price_rub": price,
        "price_per_km": _num(parsed.get("price_per_km")),
        "tonnage": _num(parsed.get("tonnage")),
        "body": _norm_body(parsed.get("body")),
        "route_km": route_km,
        "raw_text": str(parsed.get("raw_text") or text)[:2000],
    }


async def vision_openai(image_bytes: bytes, mime: str) -> dict[str, Any]:
    key = (getattr(config, "OPENAI_API_KEY", "") or "").strip()
    if not key:
        return {}
    base = (getattr(config, "OPENAI_BASE_URL", "") or "https://api.openai.com/v1").rstrip("/")
    model = (getattr(config, "OPENAI_VISION_MODEL", "") or "gpt-4o-mini").strip()
    payload_bytes, payload_mime = _prepare_vision_image(image_bytes, mime)
    b64 = base64.b64encode(payload_bytes).decode("ascii")
    data_url = f"data:{payload_mime};base64,{b64}"
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
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(90.0, connect=15.0)) as client:
            r = await client.post(f"{base}/chat/completions", headers=headers, json=payload)
            if r.status_code >= 400:
                log.warning("openai vision %s: %s", r.status_code, r.text[:300])
                return {}
            data = r.json()
    except httpx.TimeoutException as exc:
        log.warning("openai vision timeout: %s", exc)
        return {}
    except Exception as exc:
        log.warning("openai vision failed: %s", exc)
        return {}
    try:
        text = data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError):
        return {}
    parsed = _parse_json_loose(text if isinstance(text, str) else str(text))
    route_km = _num(parsed.get("route_km"))
    price = _sane_price_rub(_num(parsed.get("price_rub")), raw=str(text), route_km=route_km)
    return {
        "board": parsed.get("board") or _detect_board(str(parsed.get("raw_text") or text)),
        "from_city": _norm_city(parsed.get("from_city")),
        "to_city": _norm_city(parsed.get("to_city")),
        "price_rub": price,
        "price_per_km": _num(parsed.get("price_per_km")),
        "tonnage": _num(parsed.get("tonnage")),
        "body": _norm_body(parsed.get("body")),
        "route_km": route_km,
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


def _prepare_vision_image(image_bytes: bytes, mime: str) -> tuple[bytes, str]:
    """Downscale/compress large screenshots so vision APIs respond faster."""
    if len(image_bytes) <= 900_000:
        return image_bytes, mime
    try:
        from PIL import Image

        img = Image.open(BytesIO(image_bytes))
        if img.mode not in ("RGB", "L"):
            img = img.convert("RGB")
        elif img.mode == "L":
            img = img.convert("RGB")
        w, h = img.size
        longest = max(w, h)
        if longest > 1600:
            scale = 1600 / float(longest)
            img = img.resize((max(1, int(w * scale)), max(1, int(h * scale))), Image.Resampling.LANCZOS)
        out = BytesIO()
        img.save(out, format="JPEG", quality=82, optimize=True)
        compressed = out.getvalue()
        if compressed and len(compressed) < len(image_bytes):
            return compressed, "image/jpeg"
    except Exception as exc:
        log.debug("vision resize skipped: %s", exc)
    return image_bytes, mime


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

    # Prefer vision when configured (timeouts/errors → empty → OCR fallback)
    if (getattr(config, "GEMINI_API_KEY", "") or "").strip():
        try:
            vision_fields = await vision_gemini(image_bytes, mime)
        except Exception as exc:
            log.warning("gemini extract crashed: %s", exc)
            vision_fields = {}
        if vision_fields.get("from_city") or vision_fields.get("to_city"):
            methods.append("gemini")
    if not vision_fields.get("from_city") and not vision_fields.get("to_city"):
        if (getattr(config, "OPENAI_API_KEY", "") or "").strip():
            try:
                vision_fields = await vision_openai(image_bytes, mime)
            except Exception as exc:
                log.warning("openai extract crashed: %s", exc)
                vision_fields = {}
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
                else " или задайте GEMINI_API_KEY для точного разбора скринов бирж"
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
    Decide destination for backhaul math and listed offer from the ad card.

    Carrier base is usually Москва. Destination = far end of the trip
    (city that is not the base). Listed board rate becomes offer_rub.
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
        "board": fields.get("board"),
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
