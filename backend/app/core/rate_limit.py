"""Счётчики попыток в Redis (N-06): фиксированное окно, атомарно через MULTI/EXEC."""

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass

from redis import Redis

from app.core.errors import ApiError, rate_limited

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


@contextmanager
def reserve(
    redis: Redis, key: str, window_seconds: int, limit: int, message: str
) -> Iterator[None]:
    """Лимит на созданные объекты, а не на попытки (ADR 0017 п. 7–8: «10 тикетов в час»).

    Попытка учитывается сразу (параллельные запросы не обойдут лимит), а отказ — ошибка
    проверки или сбой — возвращает её в окно: исправленный запрос клиент повторит без 429.
    Отказ 429 тоже возвращает свою попытку: счётчик = успешные + выполняющиеся.
    """
    try:
        enforce(redis, key, window_seconds, limit, message)
    except ApiError:
        undo_hit(redis, key)
        raise
    try:
        yield
    except BaseException:
        undo_hit(redis, key)
        raise


# Места одновременных подключений (ADR 0028 п. 15): множество с арендой — член = подключение,
# балл = срок аренды по часам Redis. Истёкшие аренды (процесс упал, не освободив место)
# вычищаются при следующем захвате, поэтому место не теряется навсегда.
# Время — с микросекундами: при целых секундах аренда, продлённая в конце секунды, истекала
# бы раньше срока.
_NOW = "local t = redis.call('TIME') local now = tonumber(t[1]) + tonumber(t[2]) / 1000000\n"
_ACQUIRE_SLOT = (
    _NOW
    + """
redis.call('ZREMRANGEBYSCORE', KEYS[1], '-inf', now)
if redis.call('ZCARD', KEYS[1]) >= tonumber(ARGV[1]) then return 0 end
redis.call('ZADD', KEYS[1], now + tonumber(ARGV[2]), ARGV[3])
redis.call('EXPIRE', KEYS[1], math.ceil(tonumber(ARGV[2])))
return 1
"""
)
_RENEW_SLOT = (
    _NOW
    + """
redis.call('ZADD', KEYS[1], 'XX', now + tonumber(ARGV[1]), ARGV[2])
redis.call('EXPIRE', KEYS[1], math.ceil(tonumber(ARGV[1])))
return 1
"""
)


@dataclass
class Slot:
    """Место подключения в общем для всех процессов лимите (`ws_max_sockets_per_user`).

    Аренда продлевается, пока подключение живо (`renew` не реже чем раз в `lease_seconds`).
    """

    redis: Redis
    key: str
    member: str
    lease_seconds: float

    def acquire(self, limit: int) -> bool:
        script = self.redis.register_script(_ACQUIRE_SLOT)
        return bool(script(keys=[PREFIX + self.key], args=[limit, self.lease_seconds, self.member]))

    def renew(self) -> None:
        self.redis.register_script(_RENEW_SLOT)(
            keys=[PREFIX + self.key], args=[self.lease_seconds, self.member]
        )

    def release(self) -> None:
        self.redis.zrem(PREFIX + self.key, self.member)
