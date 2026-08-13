"""Unit tests for ATI screenshot field parsing (no vision/OCR)."""

from app.screenshot_offer import fields_from_text, resolve_analyze_targets


def test_fields_from_ati_like_text():
    text = (
        "ATI.SU груз\n"
        "Москва → Тула\n"
        "10 т тент\n"
        "ставка 28 000 ₽\n"
        "174 км\n"
    )
    f = fields_from_text(text)
    assert f["from_city"] and "москв" in f["from_city"]
    assert f["to_city"] and "тул" in f["to_city"]
    assert f["price_rub"] == 28000
    assert f["tonnage"] == 10
    assert f["body"] == "tent"
    assert f["route_km"] == 174


def test_resolve_outbound_from_base():
    t = resolve_analyze_targets(
        {"from_city": "москва", "to_city": "тула", "price_rub": 25000},
        base="москва",
    )
    assert t["destination"] == "тула"
    assert t["direction"] == "outbound"
    assert t["offer_rub"] == 25000


def test_resolve_inbound_to_base():
    t = resolve_analyze_targets(
        {"from_city": "казань", "to_city": "москва", "price_rub": 40000},
        base="москва",
    )
    assert t["destination"] == "казань"
    assert t["direction"] == "inbound"
