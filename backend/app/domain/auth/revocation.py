"""Отзыв access-токенов до истечения срока (Глава 25, ADR 0029 п. 12, #102).

Access — JWT на 15 минут; refresh отзывается в БД, но без этого модуля выданный access жил бы
до конца срока и после выхода или смены пароля. Две отметки в Redis, обе живут не дольше
срока access-токена:
- `auth:revoked-jti:{jti}` — один токен (выход): TTL — остаток его жизни;
- `auth:revoked-since:{user_id}` — все токены пользователя, выпущенные раньше момента T (сброс и
  смена пароля, блокировка, отзыв согласия, повторное предъявление refresh): TTL — срок access.
Проверка — один MGET на запрос. Время — в миллисекундах (claim `iat_ms`): новая пара после
смены пароля выпускается сразу после отметки и остаётся действительной.
Redis недоступен — 503: доступ без проверки отзыва не выдаётся (fail closed).
"""

from datetime import UTC, datetime

from redis import Redis
from redis.exceptions import RedisError

from app.core.config import Settings
from app.core.errors import ApiError
from app.core.security import AccessClaims

JTI_PREFIX = "auth:revoked-jti:"
SINCE_PREFIX = "auth:revoked-since:"


def _unavailable(exc: RedisError) -> ApiError:
    return ApiError(503, "SERVICE_UNAVAILABLE", "Сервис временно недоступен, повторите позже")


def revoke_token(redis: Redis, claims: AccessClaims, now: datetime | None = None) -> None:
    """Выход: предъявленный access-токен больше не принимается."""
    left = int((claims.expires_at - (now or datetime.now(UTC))).total_seconds()) + 1
    if left <= 0:
        return  # уже истёк
    try:
        redis.set(JTI_PREFIX + claims.jti, 1, ex=left)
    except RedisError as exc:
        raise _unavailable(exc) from exc


def revoke_user_tokens(
    redis: Redis, settings: Settings, user_id: int, now: datetime | None = None
) -> None:
    """Все access-токены пользователя, выпущенные до этого момента, больше не принимаются."""
    since = int((now or datetime.now(UTC)).timestamp() * 1000)
    try:
        redis.set(SINCE_PREFIX + str(user_id), since, ex=settings.access_token_ttl_seconds + 60)
    except RedisError as exc:
        raise _unavailable(exc) from exc


def is_revoked(redis: Redis, claims: AccessClaims) -> bool:
    try:
        jti, since = redis.mget(JTI_PREFIX + claims.jti, SINCE_PREFIX + str(claims.user_id))
    except RedisError as exc:
        raise _unavailable(exc) from exc
    return jti is not None or (since is not None and claims.issued_at_ms < int(since))
