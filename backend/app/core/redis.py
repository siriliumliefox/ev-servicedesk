"""Клиент Redis: SMS-коды, счётчики rate limiting (ADR 0005) и события тикетов (ADR 0017)."""

from collections.abc import AsyncIterator
from functools import lru_cache

from redis import Redis
from redis.asyncio import Redis as AsyncRedis

from app.core.config import get_settings


@lru_cache
def _client() -> Redis:
    return Redis.from_url(get_settings().redis_url, decode_responses=True)


def get_redis() -> Redis:
    """Зависимость FastAPI; в тестах подменяется (fakeredis или тестовая БД Redis)."""
    return _client()


async def get_pubsub_redis() -> AsyncIterator[AsyncRedis]:
    """Асинхронный клиент на одно WebSocket-подключение (подписка pub/sub занимает соединение).

    Создаётся в цикле событий подключения и закрывается вместе с ним; в тестах подменяется.
    """
    client = AsyncRedis.from_url(get_settings().redis_url, decode_responses=True)
    try:
        yield client
    finally:
        await client.aclose()
