"""How-to guides for commercial scrape API keys (admin UI)."""

from __future__ import annotations

from typing import Any

# Structured guides for sources that need paid/contract API access.
API_SOURCE_GUIDES: dict[str, dict[str, Any]] = {
    "contour": {
        "source": "contour",
        "display_name": "Контур.Закупки",
        "website": "https://zakupki.kontur.ru/",
        "signup_url": "https://zakupki.kontur.ru/site/articles/80360-api_bez_kodov_i_paniki",
        "url_hint": (
            "URL API gateway из документации Контура / кабинета интегратора "
            "(уточните у менеджера; не HTML главной zakupki.kontur.ru)."
        ),
        "env_names": ["CONTOUR_API_URL", "CONTOUR_API_TOKEN"],
        "paid_note": "Доступ платный: модуль API / тариф «Поиск» — через менеджера или заявку.",
        "steps": [
            "Зарегистрироваться или войти на zakupki.kontur.ru.",
            "Оставить заявку на API («Модуль API для CRM» / тариф «Поиск») через менеджера или форму на сайте.",
            "После оплаты получить доступ в Кабинет Интегратора на email.",
            "В кабинете выпустить API-ключ.",
            "Вставить в наш UI: URL эндпоинта из их docs + токен. Типичный контакт: zakupki.api@skbkontur.ru.",
        ],
    },
    "tenderplan": {
        "source": "tenderplan",
        "display_name": "Tenderplan",
        "website": "https://tenderplan.ru/",
        "signup_url": "https://tenderplan.ru/",
        "url_hint": "Base URL JSON API из личного кабинета / письма поддержки (не HTML сайта).",
        "env_names": ["TENDERPLAN_API_URL", "TENDERPLAN_API_TOKEN"],
        "paid_note": "API часто только по тарифу или договору — уточните в поддержке tenderplan.",
        "steps": [
            "Зарегистрироваться или войти на tenderplan.ru.",
            "Личный кабинет → раздел API / Интеграции (или запрос менеджеру).",
            "Подключить тариф с API, если он продаётся отдельно.",
            "Создать токен / ключ доступа.",
            "Вставить URL + token в наш Мониторинг. Если API только по договору — напишите в поддержку Tenderplan.",
        ],
    },
    "tenderland": {
        "source": "tenderland",
        "display_name": "Tenderland",
        "website": "https://tenderland.ru/",
        "signup_url": "https://tenderland.ru/",
        "url_hint": "Base URL API + токен из договора / ЛК (уточните у поддержки).",
        "env_names": ["TENDERLAND_API_URL", "TENDERLAND_API_TOKEN"],
        "paid_note": "Доступ к API обычно по договору с менеджером / поддержкой.",
        "steps": [
            "Зарегистрироваться или войти на tenderland.ru.",
            "В личном кабинете найти API / Интеграции или запросить доступ у поддержки.",
            "Заключить договор / подключить тариф с API при необходимости.",
            "Получить base URL и API-токен.",
            "Вставить URL + token в наш Мониторинг → API ключи.",
        ],
    },
    "synapse": {
        "source": "synapse",
        "display_name": "Synapse",
        "website": "https://synapsenet.ru/",
        "signup_url": "https://synapsenet.ru/",
        "url_hint": "Endpoint API + ключ из ЛК Synapse или от менеджера.",
        "env_names": ["SYNAPSE_API_URL", "SYNAPSE_API_TOKEN"],
        "paid_note": "Доступ платный / по договору — через ЛК или менеджера Synapse.",
        "steps": [
            "Зарегистрироваться или войти на synapsenet.ru.",
            "Личный кабинет → API / интеграции или заявка менеджеру.",
            "Подключить доступ к API (часто по тарифу или договору).",
            "Получить endpoint и API key.",
            "Вставить URL + ключ в наш Мониторинг → API ключи.",
        ],
    },
}


def get_api_source_guide(source: str) -> dict[str, Any] | None:
    return API_SOURCE_GUIDES.get(source)


def list_api_source_guides() -> list[dict[str, Any]]:
    return [API_SOURCE_GUIDES[k] for k in ("contour", "tenderplan", "tenderland", "synapse")]
