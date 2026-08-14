"""Golden cases from live TG feed: aliases, customs, noise, junk cities."""

from freight_core.parse import parse_load, parse_load_blocks


def test_navoi_mytishchi_not_kubinka():
    p = parse_load(
        "Погрузка завтра\n"
        "Навои (Нур Ота) → Московская обл. (Мытищи)\n"
        "Растаможка - Кубинка\n"
        "2та тент станд."
    )
    assert p.from_city == "навои"
    assert p.to_city == "мытищи"
    assert p.kind != "noise"


def test_tambov_toshkent_not_imo():
    p = parse_load("Тамбов Тошкент\n\nТент фура кере 6 та\n\n950401398 телеграм варсап и имо")
    assert p.from_city == "тамбов"
    assert p.to_city == "ташкент"
    assert p.to_city != "имо"


def test_tolyatti_xorazm_alias():
    p = parse_load("Толятти - Хоразм\nКапак. 23,5 тн\nТент 25 шт")
    assert p.from_city == "тольятти"
    assert p.to_city == "ургенч"


def test_junk_mega_paravoz_not_route():
    p = parse_load("Мега/паравоз 1\n\nМинск\nСамарқанд\nТахта 39 тон\nТент 1")
    assert p.from_city != "мега"
    assert p.to_city != "паравоз"
    if p.from_city and p.to_city:
        assert p.from_city == "минск"
        assert p.to_city == "самарканд"


def test_noise_job_no_cities():
    p = parse_load("На завтра 1 человек выкопать траншею, 540 руб./час + обед")
    assert p.kind == "noise"
    assert p.from_city is None
    assert p.to_city is None


def test_noise_vacancy():
    p = parse_load(
        "💰 Нужен дополнительный доход?\n"
        "📍 Вакансии доступны по всей России\n"
        "💵 От 100 000 ₽ в неделю"
    )
    assert p.kind == "noise"
    assert not p.from_city and not p.to_city


def test_welcome_bot_noise():
    p = parse_load(
        "Борис Денисов, добро пожаловать в группу ГРУЗОПЕРЕВОЗКИ - ЛОГИСТИКА.\n"
        "@Easymoderbot — самый нескучный бот-модератор"
    )
    assert p.kind == "noise"
    assert p.to_city not in {"самый", "логистика"}


def test_aktualnyy_gruz_navoi_kyzylorda():
    p = parse_load(
        "🚛🔥 АКТУАЛЬНЫЙ ГРУЗ! 🔥🚛\n"
        "📍 НАВОИ, UZ → КЫЗЫЛОРДА, KZ\n"
        "🧱 Груз: Минеральная вата\n"
        "📅 Погрузка: завтра\n"
        "🛃 Таможня: Яллама"
    )
    assert p.from_city == "навои"
    assert p.to_city == "кызылорда"
    assert p.from_city != "актуальный"


def test_toshkent_moscow_not_narxi():
    p = parse_load("Тошкент- Москва\nУзум бозор 3 кун\nРеф режимда 2 та керак\nНархи 3500")
    assert p.from_city == "ташкент"
    assert p.to_city == "москва"
    assert p.to_city != "нархи"


def test_fryazino_dushanbe_still_works():
    p = parse_load("Фрязино Душанбе\nРеф без режм")
    assert p.from_city == "фрязино"
    assert p.to_city == "душанбе"


def test_noise_blocks_empty():
    blocks = parse_load_blocks("Погладить скатерти для банкета. 3 часа. 4000 ₽.")
    assert blocks == []
