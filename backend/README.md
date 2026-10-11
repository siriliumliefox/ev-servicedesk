# EV-ServiceDesk backend

FastAPI, Python 3.12, Poetry 2.5.1, SQLAlchemy 2, Alembic, PostgreSQL 16, Redis 7.
Контракт — [`docs/openapi.yaml`](../docs/openapi.yaml), маршруты API — под `/v1`.

## Запуск локально
```bash
docker compose up -d postgres redis      # из корня репозитория
cd backend
poetry install
poetry run alembic upgrade head
poetry run uvicorn app.main:app --reload # http://localhost:8000/docs — Swagger UI
```

## Auth Service (Глава 10, ADR 0005, 0013)
| Операция | Путь |
|---|---|
| Запросить SMS-код | `POST /v1/auth/phone/request-code` |
| Подтвердить код (вход/регистрация клиента) | `POST /v1/auth/phone/verify-code` |
| Обновить токены | `POST /v1/auth/refresh` |
| Выход | `POST /v1/auth/logout` |
| Отозвать согласие на ПД | `DELETE /v1/auth/pd-consent` |
| Вход персонала по паролю | `POST /v1/auth/staff/login` |
| Привязать Telegram | `POST /v1/auth/telegram/link` |
| Профиль | `GET /v1/me` |

Локально (`ENVIRONMENT=local`, `SMS_PROVIDER=fake`) SMS не отправляется, код в логи не
пишется; получить его можно только так:
```bash
curl 'http://localhost:8000/v1/_debug/sms/last-code?phone=%2B375291234567'
```
Вне local этого маршрута нет. Переменные окружения — [`.env.example`](../.env.example).

Реальные SMS через A1 (`SMS_PROVIDER=a1`): IP машины должен быть разрешён в A1.
Проверить ключ, IP и альфа-имя (ключ вводится скрыто): `python3 ../scripts/a1_check.py --sender ETSGOMEL`.

## Структура
| Путь | Назначение |
|---|---|
| `app/api/` | HTTP: маршруты, схемы, зависимости аутентификации и RBAC |
| `app/domain/` | Доменная логика (auth, «светофор» агрегатов) — без HTTP |
| `app/core/` | Настройки, ошибки, криптография, БД, Redis |
| `app/models/` | ORM; схема — только через Alembic |
| `tests/auth/` | Unit: токены, коды и TTL, лимиты, адаптер A1 |
| `tests/api/` | Интеграция на реальных Postgres и Redis: сценарии, безопасность, контракт, нагрузка |

## Проверки
```bash
poetry run ruff check .
poetry run pytest -q        # нужны Postgres (*_test) и Redis; в CI REQUIRE_DB=1, REQUIRE_REDIS=1
../scripts/smoke_backend_image.sh backend:smoke   # после docker build -t backend:smoke .
```
