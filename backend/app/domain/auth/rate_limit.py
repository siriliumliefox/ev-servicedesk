"""Счётчики попыток в Redis (N-06): фиксированное окно, атомарно через MULTI/EXEC."""

from dataclasses import dataclass

from redis import Redis

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


def peek(redis: Redis, key: str) -> Hit:
    """Текущее значение счётчика без увеличения."""
    full_key = PREFIX + key
    with redis.pipeline(transaction=True) as pipe:
        pipe.get(full_key)
        pipe.ttl(full_key)
        count, ttl = pipe.execute()
    return Hit(count=int(count or 0), retry_after=int(ttl) if ttl and ttl > 0 else 0)


def acquire_cooldown(redis: Redis, key: str, seconds: int) -> int:
    """Пауза между событиями: 0 — пауза взята; иначе — сколько секунд ждать."""
    full_key = PREFIX + key
    if redis.set(full_key, 1, ex=seconds, nx=True):
        return 0
    ttl = redis.ttl(full_key)
    return int(ttl) if ttl and ttl > 0 else seconds


def reset(redis: Redis, *keys: str) -> None:
    redis.delete(*(PREFIX + k for k in keys))
