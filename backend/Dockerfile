# EV-ServiceDesk backend — production-подобный образ (Глава 4, шаг 3 / основа для Главы 26)
FROM python:3.12-slim

# ENVIRONMENT=production по умолчанию: образ без явного окружения не стартует с
# секретами-заглушками и без отладочных маршрутов (fail closed, ADR 0013).
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    POETRY_VIRTUALENVS_CREATE=false \
    ENVIRONMENT=production

RUN pip install --no-cache-dir poetry==2.5.1

WORKDIR /app

COPY pyproject.toml poetry.lock ./
RUN poetry install --only main --no-root --no-interaction

COPY app ./app
# Миграции в образе: `alembic upgrade head` выполняется перед стартом (Глава 26).
COPY alembic.ini ./
COPY alembic ./alembic

# Процессов uvicorn (Глава 24, ADR 0028 п. 15): Python занимает одно ядро на процесс; сервер —
# 2 vCPU. uvicorn читает WEB_CONCURRENCY сам; лимит WebSocket на пользователя общий (Redis).
# Пул БД на процесс — DB_POOL_SIZE + DB_MAX_OVERFLOW: процессы × пул ≤ max_connections PostgreSQL.
ENV WEB_CONCURRENCY=2

EXPOSE 8000
# Сначала проверка настроек и бакета в одном процессе (app.preflight): упавший при старте процесс
# uvicorn супервизор перезапустил бы, и контейнер с неверной конфигурацией не завершился бы.
CMD ["sh", "-c", "python -m app.preflight && exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --no-access-log"]
