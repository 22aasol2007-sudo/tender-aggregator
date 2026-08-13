# Freight Hub

Сайт с единой лентой заявок из **Telegram** и бесплатных агрегаторов.

## Архитектура (v0.3)

- Общее ядро: [`freight_core/`](../freight_core/) — parse / score / geo / defaults
- **Hub владеет Telethon** (один session-файл). Бот с `USE_HUB_INGEST=1` только шлёт алерты из `hub.db`
- Источники: Telethon live+backfill, `tg_public` (t.me/s), PapaCargo, Перевозка24, ATI stub (нужен `ATI_API_TOKEN`)

## Быстрый старт

```powershell
cd C:\Users\windo\Projects\tender-aggregator\freight-hub
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy .env.example .env
python setup_check.py
```

1. VPN (если `t.me` не открывается)
2. `API_ID` / `API_HASH` в `.env` с [my.telegram.org](https://my.telegram.org)
3. `python login_tg.py`
4. `python -m app.main` → http://127.0.0.1:8088

Бот (после работающего хаба):

```
USE_HUB_INGEST=1
HUB_DB_PATH=...\freight-hub\data\hub.db
```

Не открывай Telethon в боте и хабе на **один** `.session` одновременно.

## UI

- Профиль машины (база / кузов / тоннаж / радиус / обратка)
- Фильтры: shipper-only (по умолчанию), скор ≥ 40, сорт time|score
- Телефон / @ в карточке, «Не интересно» → mute направления
- Health: resolved чатов, источники, подсказки

## API

- `GET /api/loads?shipper_only=true&min_score=40&sort=score`
- `GET|POST /api/profile`
- `POST /api/mute` · `DELETE /api/mute`
- `POST /api/scrape`
- `GET /api/health`
