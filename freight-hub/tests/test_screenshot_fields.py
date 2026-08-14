"""Screenshot / OCR field extraction regressions (ATI-like)."""

from app.screenshot_offer import _norm_city, _sane_price_rub, fields_from_text


def test_junk_cities_rejected():
    assert _norm_city("загр") is None
    assert _norm_city("выгр") is None
    assert _norm_city("Радумля д.") == "радумля"
    assert _norm_city("Петро-Славянка п.") == "петро-славянка"


def test_nkb_not_price():
    raw = "RUS 634 км #NKB21947 реф Радумля д. Петро-Славянка п. 20 / 82"
    assert _sane_price_rub(21947, raw=raw, route_km=634) is None
    f = fields_from_text(raw)
    assert f.get("price_rub") in (None, 0) or f["price_rub"] != 21947
    assert f.get("from_city") == "радумля"
    assert f.get("to_city") == "петро-славянка"
    assert f.get("route_km") == 634
    assert f.get("tonnage") == 20
