"""Действует ли сессия access-токена (Глава 25, ADR 0029 п. 12, #102) — одно правило для REST
(`get_current_user`) и WebSocket событий тикета.

Access — JWT на 15 минут; без отзыва он жил бы до конца срока и после выхода или смены пароля.
Сессия действует, если:
- пользователь есть и доступен (не заблокирован, не анонимизирован) — роль и активность из БД;
- токен выпущен не раньше `app_user.sessions_revoked_at` — отметку ставит `tokens.revoke_all` в той
  же транзакции, что и отзыв refresh-токенов (сброс и смена пароля, блокировка, отзыв согласия,
  повтор refresh); время выпуска — claim `iat_ms`: новая пара после смены пароля действительна;
- токен не отозван выходом: `auth:revoked-jti:{jti}` в Redis с TTL — остаток жизни токена (выход
  завершает одну сессию, а не все). Redis недоступен — 503: без проверки доступ не выдаётся.
"""

from datetime import UTC, datetime

from redis import Redis
from redis.exceptions import RedisError
from sqlalchemy.orm import Session

from app.core.errors import ApiError, unauthorized
from app.core.security import AccessClaims
from app.models import AppUser

JTI_PREFIX = "auth:revoked-jti:"


def _unavailable() -> ApiError:
    return ApiError(503, "SERVICE_UNAVAILABLE", "Сервис временно недоступен, повторите позже")


def revoke_token(redis: Redis, claims: AccessClaims) -> None:
    """Выход: предъявленный access-токен больше не принимается."""
    left = int((claims.expires_at - datetime.now(UTC)).total_seconds()) + 1
    if left <= 0:
        return  # уже истёк
    try:
        redis.set(JTI_PREFIX + claims.jti, 1, ex=left)
    except RedisError as exc:
        raise _unavailable() from exc


def authenticate(db: Session, redis: Redis, claims: AccessClaims) -> AppUser:
    """Пользователь действующей сессии токена, иначе 401."""
    user = db.get(AppUser, claims.user_id, populate_existing=True)
    if user is None or not user.is_available:
        raise unauthorized("Учётная запись недоступна")
    revoked_at = user.sessions_revoked_at
    if revoked_at is not None and claims.issued_at_ms < int(revoked_at.timestamp() * 1000):
        raise unauthorized("Сессия завершена — войдите заново")
    try:
        logged_out = redis.exists(JTI_PREFIX + claims.jti)
    except RedisError as exc:
        raise _unavailable() from exc
    if logged_out:
        raise unauthorized("Сессия завершена — войдите заново")
    return user
