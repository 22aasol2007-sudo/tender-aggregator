"""Primary GTM niche: cosmetics companies in Moscow × corrugated packaging."""

from __future__ import annotations

NICHE_ID = "cosmetics_moscow_gofra"
NICHE_TITLE = "Косметика Москвы · гофроупаковка"
NICHE_CITY_DEFAULT = "Москва"

# Pilot mode: lower k-anonymity so early design partners still get named shortlists
PILOT_MIN_SHARE_N = 3
DEFAULT_MIN_SHARE_N = 5

GOFRA_ATTRIBUTES = (
    "flute",       # T/B/C/E/F / 3-слой / 5-слой
    "grade",       # марка картона T-23, T-24...
    "length_mm",
    "width_mm",
    "height_mm",
    "color",       # бурый / белый / мелованный
    "print",       # без печати / флекс / офсет
    "qty",
    "unit",        # шт
)

GOFRA_FLUTE_ALIASES = {
    "т": "t",
    "t": "t",
    "т-23": "t23",
    "t-23": "t23",
    "t23": "t23",
    "т23": "t23",
    "трехслой": "3ply",
    "трёхслой": "3ply",
    "3-слой": "3ply",
    "3слой": "3ply",
    "пятислой": "5ply",
    "5-слой": "5ply",
    "5слой": "5ply",
    "е": "e",
    "e": "e",
    "b": "b",
    "c": "c",
    "bc": "bc",
}

# Search terms for EIS contracts / tenders related to packaging for cosmetics
GOFRA_SEARCH_TERMS = [
    "гофрокороб",
    "гофроящик",
    "гофрокартон",
    "гофрированный картон",
    "картонная упаковка",
    "короба картонные",
    "упаковка из гофрокартона",
]

COSMETICS_CONTEXT_TERMS = [
    "косметик",
    "парфюмер",
    "крем",
    "шампунь",
    "уход за кожей",
    "beauty",
]

DESIGN_PARTNER_RULES = {
    "max_free_deals": 2,
    "max_free_days": 30,
    "required": [
        "supplier_book_export",
        "rfq_feedback",
        "share_consent_or_private_only_ack",
        "execution_feedback",
    ],
    "success_criteria": [
        "comparable_table",
        "at_least_one_measured_saving_or_speedup",
    ],
}


def normalize_gofra_attrs(raw: dict | None) -> dict:
    """Normalize corrugated box attributes for fingerprinting."""
    if not raw:
        return {}
    out: dict = {}
    flute = str(raw.get("flute") or "").casefold().strip()
    if flute:
        # map common aliases
        key = flute.replace(" ", "")
        for a, v in [
            ("трёхслой", "3ply"),
            ("трехслой", "3ply"),
            ("3-слой", "3ply"),
            ("3слой", "3ply"),
            ("пятислой", "5ply"),
            ("5-слой", "5ply"),
            ("5слой", "5ply"),
            ("t-23", "t23"),
            ("т-23", "t23"),
            ("т23", "t23"),
        ]:
            if a in key:
                key = v
                break
        out["flute"] = key[:32]
    if raw.get("grade"):
        out["grade"] = str(raw["grade"]).casefold().replace(" ", "").replace("-", "")[:32]
    for dim in ("length_mm", "width_mm", "height_mm"):
        try:
            if raw.get(dim) is not None:
                out[dim] = int(float(raw[dim]))
        except (TypeError, ValueError):
            pass
    if raw.get("color"):
        out["color"] = str(raw["color"]).casefold()[:32]
    if raw.get("print"):
        out["print"] = str(raw["print"]).casefold()[:32]
    return out


def attrs_fingerprint_part(attrs: dict | None) -> str:
    a = normalize_gofra_attrs(attrs)
    if not a:
        return ""
    parts = []
    for k in ("flute", "grade", "length_mm", "width_mm", "height_mm", "color", "print"):
        if k in a:
            parts.append(f"{k}={a[k]}")
    return "|".join(parts)


def niche_payload() -> dict:
    return {
        "id": NICHE_ID,
        "title": NICHE_TITLE,
        "city_default": NICHE_CITY_DEFAULT,
        "pilot_min_share_n": PILOT_MIN_SHARE_N,
        "attributes": list(GOFRA_ATTRIBUTES),
        "search_terms": GOFRA_SEARCH_TERMS,
        "cosmetics_context": COSMETICS_CONTEXT_TERMS,
        "design_partner_rules": DESIGN_PARTNER_RULES,
        "phase": {
            "now": "gofra_carton_only",
            "next": ["labels_bottles_flexible"],
            "later": ["ingredients", "contract_manufacturing"],
        },
    }
