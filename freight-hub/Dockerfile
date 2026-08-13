# Build from repo root: docker build -f freight-hub/Dockerfile .
FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app \
    HOST=0.0.0.0 \
    PORT=8088 \
    DB_PATH=/data/hub.db \
    MAX_CACHE_DIR=/data/max_cache \
    SESSION_NAME=/data/freight_hub

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        gcc \
        tesseract-ocr \
        tesseract-ocr-rus \
    && rm -rf /var/lib/apt/lists/*

COPY freight-hub/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt

COPY freight_core /app/freight_core
COPY freight-hub /app/freight-hub

WORKDIR /app/freight-hub

RUN mkdir -p /data/max_cache \
    && chmod +x /app/freight-hub/docker-entrypoint.sh

EXPOSE 8088

CMD ["./docker-entrypoint.sh"]
