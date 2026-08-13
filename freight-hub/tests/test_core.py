"""Core observability tests: parse / score / geo."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from freight_core.geo import distance_km
from freight_core.parse import parse_load
from freight_core.score import score_load


def test_parse_shipper_route_and_phone():
    text = (
        "Есть груз Москва → Тула 20т тент. Цена 45000 руб. "
        "Погрузка завтра. Тел +7 916 123-45-67 Ищу машину."
    )
    p = parse_load(text)
    assert p.from_city and "моск" in p.from_city.lower()
    assert p.to_city and "тул" in p.to_city.lower()
    assert p.tonnage is not None and float(p.tonnage) >= 20
    assert p.phones or p.contacts


def test_geo_moscow_tula_reasonable():
    km = distance_km("москва", "тула")
    assert km is not None
    assert 100 < km < 300


def test_route_km_without_price():
    from app.ingest import calc_price_per_km

    km, ppk = calc_price_per_km(None, "москва", "тула")
    assert km is not None and 100 < km < 300
    assert ppk is None
    km2, ppk2 = calc_price_per_km("45000 руб", "москва", "тула")
    assert km2 is not None and ppk2 is not None and ppk2 > 0


def test_score_hot_shipper():
    text = "Груз реф Москва → Воронеж 20т +2. Цена 80000. Ищу машину. +79001234567"
    parsed = parse_load(text)
    user = {
        "mode": "shipper",
        "truck_profile": '{"base":"москва","radius":150,"radius_far":1500,"body":"reefer"}',
        "mute_driver_offers": 1,
        "custom_keywords": "[]",
        "directions": "[]",
        "only_reefer": 0,
    }
    result = score_load(parsed, user, min_score=40, scoring="browse")
    assert result.score >= 40


def test_parse_posted_at_ru():
    from datetime import datetime

    from app.scrapers.board_common import parse_posted_at_ru

    ref = datetime(2026, 8, 13, 16, 0, 0).timestamp()
    ts = parse_posted_at_ru("31.07 11:43 №1271678 Видное", now=ref)
    assert ts is not None
    dt = datetime.fromtimestamp(ts)
    assert dt.day == 31 and dt.month == 7 and dt.hour == 11 and dt.minute == 43
    assert parse_posted_at_ru("no date here", now=ref) is None


def test_tonnage_band():
    from app.ingest import tonnage_allowed

    assert tonnage_allowed(None) is True
    assert tonnage_allowed(5) is True
    assert tonnage_allowed(12) is True
    assert tonnage_allowed(8.5) is True
    assert tonnage_allowed(4.9) is False
    assert tonnage_allowed(12.1) is False
    assert tonnage_allowed(20) is False
    assert tonnage_allowed(1.5) is False