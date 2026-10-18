"""Пароль сотрудника (Глава 10; Глава 25, ADR 0029 пп. 11, 13–14): вход, смена своего пароля,
лимиты неудачных попыток.

Попытка учитывается ДО проверки пароля — параллельные запросы не обходят лимит; успешная проверка
её прощает — счётчики считают только неудачи. Счётчики (`rate_limit`): пара «номер + IP» (5 за
15 мин — злоумышленник со своего адреса не запирает сотрудника), IP (20 за 15 мин) и потолок на
номер (300 в час — распределённый подбор; срабатывание — WARNING с маской номера). Неверный
текущий пароль при смене — та же неудача, что при входе: смена не обходит лимит подбора.
"""

import logging
from dataclasses import dataclass

from redis import Redis
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import rate_limit
from app.core.config import Settings
from app.core.errors import ApiError, field_error, rate_limited, unauthorized
from app.core.security import hash_password, verify_password
from app.domain.auth import passwords, tokens
from app.domain.auth.service import LoginResult
from app.domain.auth.sms import mask_phone
from app.models import AppUser
from app.models.enums import STAFF_ROLES

logger = logging.getLogger(__name__)

WINDOW = 15 * 60
HOUR = 3600
TOO_MANY = "Слишком много неудачных попыток входа"


@dataclass(frozen=True)
class _Attempt:
    pair_key: str
    ip_key: str
    phone_key: str


def _attempt(redis: Redis, settings: Settings, phone: str, client_ip: str) -> _Attempt:
    """Учитывает попытку; сверх любого лимита — 429. Все счётчики растут до проверки любого из
    них, поэтому не `rate_limit.enforce`."""
    attempt = _Attempt(
        f"staff-fail:{phone}:{client_ip}", f"staff-fail-ip:{client_ip}", f"staff-fail-h:{phone}"
    )
    by_pair = rate_limit.hit(redis, attempt.pair_key, WINDOW)
    by_ip = rate_limit.hit(redis, attempt.ip_key, WINDOW)
    by_phone = rate_limit.hit(redis, attempt.phone_key, HOUR)
    if by_pair.exceeded(settings.staff_login_failures_per_phone_ip_15min):
        raise rate_limited(by_pair.retry_after, TOO_MANY)
    if by_ip.exceeded(settings.staff_login_failures_per_ip_15min):
        raise rate_limited(by_ip.retry_after, TOO_MANY)
    if by_phone.exceeded(settings.staff_login_failures_per_phone_hour):
        if by_phone.count == settings.staff_login_failures_per_phone_hour + 1:
            logger.warning("Подбор пароля сотрудника с разных адресов: %s", mask_phone(phone))
        raise rate_limited(by_phone.retry_after, TOO_MANY)
    return attempt


def _succeeded(redis: Redis, attempt: _Attempt) -> None:
    rate_limit.reset(redis, attempt.pair_key)
    rate_limit.undo_hit(redis, attempt.ip_key)
    rate_limit.undo_hit(redis, attempt.phone_key)


def clear_login_failures(redis: Redis, phone: str) -> None:
    """Сброс и смена пароля снимают блокировку входа номера со всех адресов."""
    pairs = list(redis.scan_iter(match=f"{rate_limit.PREFIX}staff-fail:{phone}:*", count=500))
    redis.delete(rate_limit.PREFIX + f"staff-fail-h:{phone}", *pairs)


def login(
    db: Session, redis: Redis, settings: Settings, phone: str, password: str, client_ip: str
) -> LoginResult:
    """POST /auth/staff/login (N-08): заблокирован или клиент — 401, как неверный пароль."""
    attempt = _attempt(redis, settings, phone, client_ip)
    user = db.scalars(select(AppUser).where(AppUser.phone == phone)).one_or_none()
    password_hash = user.password_hash if user is not None else None
    ok = verify_password(password, password_hash)  # считаем всегда — время не выдаёт номер
    if not ok or user is None or user.role not in STAFF_ROLES or not user.is_available:
        raise unauthorized("Неверный телефон или пароль")
    _succeeded(redis, attempt)
    pair = tokens.issue_pair(db, user, settings)
    db.commit()
    return LoginResult(tokens=pair, user=user)


def change_password(
    db: Session,
    redis: Redis,
    settings: Settings,
    user: AppUser,
    current_password: str,
    new_password: str,
    client_ip: str,
) -> tokens.TokenPair:
    """POST /auth/staff/password (ADR 0029 п. 14): новая пара токенов, прочие сессии отозваны."""
    if user.phone is None:  # телефон обнуляет только анонимизация — у такого нет сессий
        raise unauthorized()
    attempt = _attempt(redis, settings, user.phone, client_ip)
    if not verify_password(current_password, user.password_hash):
        raise ApiError(400, "PASSWORD_INVALID", "Неверный текущий пароль")
    _succeeded(redis, attempt)
    if new_password == current_password:
        raise field_error("new_password", "VALIDATION_ERROR", "Новый пароль совпадает с текущим")
    passwords.ensure_strong(new_password, user.phone, field="new_password")
    tokens.lock_user(db, user.id)
    db.refresh(user)
    user.password_hash = hash_password(new_password)
    tokens.revoke_all(db, user.id)  # раньше выпуска новой пары: она остаётся действительной
    pair = tokens.issue_pair(db, user, settings)
    db.commit()
    clear_login_failures(redis, user.phone)
    return pair
