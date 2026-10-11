"""Счётчики попыток в Redis (N-06): фиксированное окно, атомарно через MULTI/EXEC."""

from dataclasses import dataclass

from redis import Redis

from app.core.errors import rate_limited

# Префикс исторический (Глава 10): смена сбросила бы действующие счётчики при выкладке.
PREFIX = "auth:rl:"


@dataclass(frozen=True)
class Hit:
    count: int
    retry_after: int  # секунд до сброса окна

    def exceeded(self, limit: int) -> bool:
        return self.count > limit


def hit(redis: Redis, key: str, window_seconds: int) -> Hit:
    """Увеличивает счётчик окна; окно стартует с первого обращения."""
    full_key = PREFIX + key
    with redis.pipeline(transaction=True) as pipe:
        pipe.set(full_key, 0, ex=window_seconds, nx=True)
        pipe.incr(full_key)
        pipe.ttl(full_key)
        _, count, ttl = pipe.execute()
    return Hit(count=int(count), retry_after=int(ttl) if ttl and ttl > 0 else window_seconds)


def enforce(redis: Redis, key: str, window_seconds: int, limit: int, message: str) -> None:
    """Учитывает попытку; сверх `limit` за окно — 429 с Retry-After до сброса окна."""
    attempt = hit(redis, key, window_seconds)
    if attempt.exceeded(limit):
        raise rate_limited(attempt.retry_after, message)


def acquire_cooldown(redis: Redis, key: str, seconds: int) -> int:
    """Пауза между событиями: 0 — пауза взята; иначе — сколько секунд ждать."""
    full_key = PREFIX + key
    if redis.set(full_key, 1, ex=seconds, nx=True):
        return 0
    ttl = redis.ttl(full_key)
    return int(ttl) if ttl and ttl > 0 else seconds


def reset(redis: Redis, *keys: str) -> None:
    redis.delete(*(PREFIX + k for k in keys))


# DECR только существующего ключа: иначе получился бы счётчик -1 без TTL.
_UNDO = """
if redis.call('EXISTS', KEYS[1]) == 1 then return redis.call('DECR', KEYS[1]) end
return 0
"""


def undo_hit(redis: Redis, key: str) -> None:
    """Возвращает одно обращение в окно (событие не состоялось или было успешным)."""
    redis.register_script(_UNDO)(keys=[PREFIX + key])
