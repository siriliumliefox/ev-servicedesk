"""Клиент Redis: SMS-коды и счётчики rate limiting (ADR 0005)."""

from functools import lru_cache

from redis import Redis

from app.core.config import get_settings


@lru_cache
def _client() -> Redis:
    return Redis.from_url(get_settings().redis_url, decode_responses=True)


def get_redis() -> Redis:
    """Зависимость FastAPI; в тестах подменяется (fakeredis или тестовая БД Redis)."""
    return _client()
