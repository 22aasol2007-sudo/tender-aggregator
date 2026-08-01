# Tender Aggregator

Агрегатор закупок с автосбором **каждые 3 минуты**.

## Возможности

1. Умные фильтры + пресеты  
2. Карточка с документами/лотами (EIS XML)  
3. Дедуп и нормализация статусов  
4. Источники: ЕИС, РТС, Росэлторг, Сбер АСТ, B2B-Center, ЭТП ГПБ, ТЕК-Торг, Фабрикант, OTC, АГЗ РТ, Контур, Tenderplan, Tenderland, Synapse, Rostender, torgi.gov.ru, РНП, банк гарантий, Федресурс, Картотека  
5. Postgres (+ SQLite fallback) и FTS  
6. Telegram-алерты по сохранённым поискам  
7. Избранное / «в работу» / заметки и теги  
8. Релевантность по профилю компании  
9. История изменений цены/срока/статуса  
10. Инкрементальный сбор + очередь/retry  
11. Экспорт CSV/Excel  
12. Дашборд  
13. Мультипользователи (JWT)  
14. Сохранённые поиски со счётчиком «новых»  
15. Сравнение дублей с разных площадок  

## Запуск

```bash
# optional
docker compose up -d

cd backend
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8010

cd ../frontend
npm install
npm run dev
```

- UI: http://127.0.0.1:5173  
- API: http://127.0.0.1:8010/docs  
- Логин по умолчанию: `admin@tender.local` / `admin123`

## Воркер (обязателен при SCRAPE_VIA_WORKER=true)

По умолчанию `SCRAPE_VIA_WORKER=true`: API/scheduler только ставят задачи в очередь (`scrape` / `monitor` / `enrich`). Долгий сбор выполняет отдельный процесс:

```bash
cd backend
.venv\Scripts\activate
python -m app.worker
```

На Railway: сервис `api` (uvicorn) + сервис `worker` (та же Docker-команда `python -m app.worker`), общие `DATABASE_URL` и `SCRAPE_PROXY_URL`.

Расписание: **hot** (~1.5 мин) — ЕИС + b2b/fabrikant/otc/rostender; **cold** (~12 мин) — остальные источники.

## Деплой

### GitHub + Vercel (UI)

Фронтенд деплоится на Vercel из папки `frontend/`.

Переменная окружения в Vercel:

- `VITE_API_BASE` — URL бэкенда без хвоста `/api` (например `https://api.example.com`)

Бэкенд (FastAPI + Postgres + worker) на Vercel не размещается — нужен отдельный хост (Railway / Render / Fly / VPS + Docker Compose).

### Docker (полный стек)

```bash
docker compose up -d --build
```

UI+API через nginx: http://localhost:8080
