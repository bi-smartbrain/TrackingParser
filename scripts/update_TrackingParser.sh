#!/bin/bash
set -e

echo "=== Безопасное обновление TrackingParser ==="

# 1. Обновляем код из git
echo "1. Обновляем код..."
cd /opt/TrackingParser
git fetch origin main
git reset --hard origin/main

# 2. Пересобираем и перезапускаем сервис без лишнего даунтайма
echo "2. Пересобираем и запускаем контейнер..."
docker-compose up -d --build --remove-orphans

# 3. Чистим неиспользуемые образы и build cache (safe)
echo "3. Чистим Docker мусор (safe)..."
docker image prune -f
docker builder prune -f --filter "until=168h"

# 4. Обновляем скрипт в /opt/auto
echo "4. Обновляем /opt/auto/update_TrackingParser.sh..."
cp scripts/update_TrackingParser.sh /opt/auto/update_TrackingParser.sh
chmod +x /opt/auto/update_TrackingParser.sh

echo "=== Обновление завершено ==="
echo "=== Контейнер запущен, cleanup выполнен ==="
