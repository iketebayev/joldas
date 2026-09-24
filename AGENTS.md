# Joldas — биржа гидов (хакатон Smart City Aktau)

## Что делаем
Площадка: турфирмы и туристы находят гидов для иностранцев в Мангистау; акимат видит дефицит по языкам.

## Стек
FastAPI + asyncpg + PostgreSQL + Jinja. Прод: https://hack.ai-lab.kz (Traefik, сеть `n8n_n8n_net`, certresolver `mytlschallenge`).
Код запекается в образ — после правок: `docker compose up -d --build`.

## Правила
- Логика — в `app/services/`, роутеры тонкие.
- Любая строка интерфейса — ключ в **трёх** словарях `app/i18n/{kk,ru,en}.json`. Проверка: `python3 tests/i18n_check.py`.
- После изменений: `tests/smoke.sh` и `tests/flow.sh`, затем `python -m app.seed --reset`.
- Факты в `app/academy.py` — только с источником.
- Название — только через `APP_NAME` в `.env`.

## Грабли
- Параметры `t()` позиционные: в текстах есть подстановка `{lang}`.
- Макрос внутри `{% block %}` не видит импорт `m` — не определять макросы в блоках.
- Демо-пользователям WhatsApp не отправляется (`is_demo`).
