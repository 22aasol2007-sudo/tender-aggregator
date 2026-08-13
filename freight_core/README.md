# freight_core

Общий пакет для **freight-hub** и **freight-tg-bot**:

- `parse.py` — kind, маршрут, тоннаж, кузов, телефон, цена, дата
- `score.py` — `scoring=strict|browse`
- `geo.py` — координаты городов, radius / backhaul
- `defaults.py` — 60 чатов + `PUBLIC_TG_CHANNELS`
- `models.py` — `RawLoad`

Импорт из приложений через локальный `_bootstrap` (корень репо в `sys.path`).
