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


def test_archive_false_positive_not_on_executed_alone():
    from app.ingest import is_archived_text

    assert not is_archived_text("Заявка исполняется, нужны грузчики")
    assert is_archived_text("Заказ выполнен, в архиве")
    assert is_archived_text('data-status="completed"')
