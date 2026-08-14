"""Regression: TG multi-offers without dashes (… Душанбе)."""

from freight_core.parse import parse_load, parse_load_blocks, split_load_blocks


MSG = """‼️ Обнинск Душанбе
120ка
Погрузка 18.08

‼️ Фрязино Душанбе
Реф без режм

‼️ Дмитровск + Москва Душанбе
Тент 96 или реф
Погрузка 21.08

🌍 Егорьевск - Душанбе
Авто: реф -18
Погрузка 18 числа

‼️ Москва ( МКАД) Душанбе
Реф без редм
Погрузка 18.08
"""


def test_split_emoji_bullets():
    blocks = split_load_blocks(MSG)
    assert len(blocks) == 5


def test_dushanbe_routes():
    routes = {(p.from_city, p.to_city) for p in parse_load_blocks(MSG)}
    assert ("фрязино", "душанбе") in routes
    assert ("москва", "душанбе") in routes
    assert ("обнинск", "душанбе") in routes
    assert ("егорьевск", "душанбе") in routes
    assert ("дмитровск", "душанбе") in routes
    assert ("фрязино", "москва") not in routes


def test_space_route_single():
    p = parse_load("Фрязино Душанбе\nРеф без режм")
    assert p.from_city == "фрязино"
    assert p.to_city == "душанбе"


def test_no_false_ref_bez_city():
    p = parse_load("Реф без режм")
    assert p.from_city is None or p.from_city not in {"реф", "без"}


def test_navoi_mytishchi_not_kubinka():
    """Customs city must not become destination; region (settlement) → settlement."""
    p = parse_load(
        "Погрузка завтра\n"
        "Навои (Нур Ота) → Московская обл. (Мытищи)\n"
        "Растаможка - Кубинка\n"
        "2та тент станд."
    )
    assert p.from_city == "навои"
    assert p.to_city == "мытищи"
    assert p.to_city != "кубинка"
    assert p.from_city != "москва"
