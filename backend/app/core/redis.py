"""Клиент Redis: SMS-коды, счётчики rate limiting (ADR 0005), публикация событий тикетов.

Подписка на события (WebSocket) — асинхронное соединение `app.core.pubsub`.
"""

from functools import lru_cache

from redis import Redis

from app.core.config import get_settings


@lru_cache
def _client() -> Redis:
    return Redis.from_url(get_settings().redis_url, decode_responses=True)


def get_redis() -> Redis:
    """Зависимость FastAPI; в тестах подменяется (fakeredis или тестовая БД Redis)."""
    return _client()
