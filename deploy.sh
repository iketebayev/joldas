#!/usr/bin/env bash
# Деплой на VPS. Запускать из корня проекта.
set -euo pipefail
cd "$(dirname "$0")"
if [ -d .git ]; then
  git pull --ff-only
fi
docker compose up -d --build
docker compose ps
echo "→ https://${DOMAIN:-hack.ai-lab.kz}"
