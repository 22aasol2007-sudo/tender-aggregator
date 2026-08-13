#!/bin/sh
set -e
mkdir -p /data/max_cache

# Seed Telethon / MAX sessions from image (railway up --no-gitignore) onto the volume once.
if [ -f /app/freight-hub/freight_hub.session ] && [ ! -f /data/freight_hub.session ]; then
  cp /app/freight-hub/freight_hub.session /data/freight_hub.session
  echo "seeded /data/freight_hub.session"
fi
if [ -f /app/freight-hub/data/max_cache/freight_hub_max.db ] && [ ! -f /data/max_cache/freight_hub_max.db ]; then
  cp /app/freight-hub/data/max_cache/freight_hub_max.db /data/max_cache/freight_hub_max.db
  echo "seeded /data/max_cache/freight_hub_max.db"
fi

exec python run.py
