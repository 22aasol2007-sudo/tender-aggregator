"""GTM niche: cosmetics companies in Moscow × corrugated packaging."""

from __future__ import annotations

from app.services.niches.base import NicheClarifyField, NichePluginData

NICHE_ID = "cosmetics_moscow_gofra"
NICHE_TITLE = "Косметика Москвы · гофроупаковка"
NICHE_CITY_DEFAULT = "Москва"
PILOT_MIN_SHARE_N = 3
DEFAULT_MIN_SHARE_N = 5

GOFRA_ATTRIBUTES = (
    "flute",
    "grade",
    "length_mm",
    "width_mm",
    "height_mm",
    "color",
    "print",
    "qty",
    "unit",
)

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

SEED_TAGS = [
    "gofra",
    "гофра",
    "гофрокороб",
    "упаковка",
    "картон",
    "moscow",
    "москва",
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


class GofraCosmeticsNiche(NichePluginData):
    def __init__(self) -> None:
        super().__init__(
            id=NICHE_ID,
            title=NICHE_TITLE,
            default_city=NICHE_CITY_DEFAULT,
            search_terms=list(GOFRA_SEARCH_TERMS),
            context_terms=list(COSMETICS_CONTEXT_TERMS),
            seed_tags=list(SEED_TAGS),
            attribute_keys=list(GOFRA_ATTRIBUTES),
            clarify_fields=[
                NicheClarifyField("product", "Товар / тип короба", True),
                NicheClarifyField("city", "Город поставки", True),
                NicheClarifyField("qty", "Количество", False),
                NicheClarifyField("flute", "Слойность / профиль", False),
                NicheClarifyField("grade", "Марка картона", False),
                NicheClarifyField("length_mm", "Длина, мм", False),
                NicheClarifyField("width_mm", "Ширина, мм", False),
                NicheClarifyField("height_mm", "Высота, мм", False),
            ],
            pilot_min_share_n=PILOT_MIN_SHARE_N,
            design_partner_rules=DESIGN_PARTNER_RULES,
            phase={
                "now": "gofra_carton_only",
                "next": ["labels_bottles_flexible"],
                "later": ["ingredients", "contract_manufacturing"],
            },
        )

    def normalize_attrs(self, raw: dict | None) -> dict:
        return normalize_gofra_attrs(raw)

    def attrs_fingerprint_part(self, attrs: dict | None) -> str:
        return attrs_fingerprint_part(attrs)

    def payload(self) -> dict:
        base = super().payload()
        base["cosmetics_context"] = list(COSMETICS_CONTEXT_TERMS)
        return base


def niche_payload() -> dict:
    return GofraCosmeticsNiche().payload()
