"""Сценарии Auth Service (Глава 10): вход по SMS, вход персонала, согласие ПД, Telegram."""

from dataclasses import dataclass
from datetime import UTC, datetime

from redis import Redis
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.errors import ApiError, rate_limited, unauthorized
from app.core.security import verify_password
from app.domain.auth import codes, rate_limit, tokens
from app.models import AppUser, PdConsent
from app.models.enums import UserRole

STAFF_ROLES = {UserRole.ENGINEER, UserRole.ADMIN}


@dataclass(frozen=True)
class LoginResult:
    tokens: tokens.TokenPair
    user: AppUser
    is_new_user: bool = False


def _active_consent(db: Session, user_id: int) -> PdConsent | None:
    return db.scalars(
        select(PdConsent).where(PdConsent.user_id == user_id, PdConsent.withdrawn_at.is_(None))
    ).one_or_none()


def verify_phone_code(
    db: Session,
    redis: Redis,
    settings: Settings,
    phone: str,
    code: str,
    pd_policy_version: str | None,
) -> LoginResult:
    """POST /auth/phone/verify-code: вход или регистрация клиента (role=client)."""
    result = codes.check_code(redis, settings, phone, code)
    if result.status is codes.CodeCheck.MISSING:
        raise ApiError(400, "CODE_EXPIRED", "Код истёк или не запрашивался — запросите новый")
    if result.status is codes.CodeCheck.WRONG:
        raise ApiError(
            400, "CODE_INVALID", "Неверный код", details={"attempts_left": result.attempts_left}
        )

    user = db.scalars(select(AppUser).where(AppUser.phone == phone)).one_or_none()
    if user is not None:
        if user.role in STAFF_ROLES:
            # Персонал входит только по паролю: SMS не должен обходить второй фактор.
            raise ApiError(400, "STAFF_PASSWORD_LOGIN", "Для сотрудников — вход по паролю")
        if not user.is_active:
            raise ApiError(400, "ACCOUNT_DISABLED", "Вход заблокирован администратором")

    consent = _active_consent(db, user.id) if user is not None else None
    if consent is None and not pd_policy_version:
        # Код не расходуется: клиент повторит запрос с согласием (99-З, ст. 5).
        raise ApiError(
            422,
            "PD_CONSENT_REQUIRED",
            "Требуется согласие на обработку персональных данных",
        )

    if not codes.consume_code(redis, phone):
        raise ApiError(400, "CODE_EXPIRED", "Код уже использован — запросите новый")
    rate_limit.reset(redis, f"verify-fail:{phone}")

    is_new = user is None
    if user is None:
        user = AppUser(phone=phone, role=UserRole.CLIENT)
        db.add(user)
        try:
            db.flush()
        except IntegrityError:
            # Параллельная регистрация того же номера: берём созданного пользователя.
            db.rollback()
            user = db.scalars(select(AppUser).where(AppUser.phone == phone)).one()
            is_new = False
            consent = _active_consent(db, user.id)

    if pd_policy_version and (consent is None or consent.policy_version != pd_policy_version):
        if consent is not None:
            consent.withdrawn_at = datetime.now(UTC)  # согласие с новой редакцией заменяет старое
            db.flush()
        db.add(PdConsent(user_id=user.id, policy_version=pd_policy_version))

    pair = tokens.issue_pair(db, user, settings)
    db.commit()
    db.refresh(user)
    return LoginResult(tokens=pair, user=user, is_new_user=is_new)


def staff_login(
    db: Session, redis: Redis, settings: Settings, phone: str, password: str, client_ip: str
) -> LoginResult:
    """POST /auth/staff/login: пароль argon2id, лимит неудачных попыток (N-06, N-08)."""
    window = 15 * 60
    by_phone = rate_limit.peek(redis, f"staff-fail:{phone}")
    by_ip = rate_limit.peek(redis, f"staff-fail-ip:{client_ip}")
    if by_phone.count >= settings.staff_login_failures_per_phone_15min:
        raise rate_limited(by_phone.retry_after, "Слишком много неудачных попыток входа")
    if by_ip.count >= settings.staff_login_failures_per_ip_15min:
        raise rate_limited(by_ip.retry_after, "Слишком много неудачных попыток входа")

    user = db.scalars(select(AppUser).where(AppUser.phone == phone)).one_or_none()
    password_hash = user.password_hash if user is not None else None
    ok = verify_password(password, password_hash)  # считаем всегда — время не выдаёт номер
    if not ok or user is None or user.role not in STAFF_ROLES or not user.is_active:
        rate_limit.hit(redis, f"staff-fail:{phone}", window)
        rate_limit.hit(redis, f"staff-fail-ip:{client_ip}", window)
        raise unauthorized("Неверный телефон или пароль")

    rate_limit.reset(redis, f"staff-fail:{phone}")
    pair = tokens.issue_pair(db, user, settings)
    db.commit()
    return LoginResult(tokens=pair, user=user)


def withdraw_pd_consent(db: Session, user: AppUser) -> None:
    """DELETE /auth/pd-consent (99-З, ст. 10): отзыв + завершение всех сессий.

    Анонимизация по очереди `ix_pd_consent_withdrawn_at` (≤ 15 дней) — фоновая задача, ADR 0013.
    """
    consent = db.scalars(
        select(PdConsent)
        .where(PdConsent.user_id == user.id, PdConsent.withdrawn_at.is_(None))
        .with_for_update()
    ).one_or_none()
    if consent is None:
        raise ApiError(409, "PD_CONSENT_NOT_ACTIVE", "Действующего согласия нет")
    consent.withdrawn_at = datetime.now(UTC)
    tokens.revoke_all(db, user.id)
    db.commit()


def link_telegram(db: Session, user: AppUser, telegram_id: str) -> AppUser:
    """POST /auth/telegram/link: один Telegram — один аккаунт."""
    owner = db.scalars(select(AppUser).where(AppUser.telegram_id == telegram_id)).one_or_none()
    if owner is not None and owner.id != user.id:
        raise ApiError(409, "TELEGRAM_ALREADY_LINKED", "Telegram привязан к другому аккаунту")
    user.telegram_id = telegram_id
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise ApiError(
            409, "TELEGRAM_ALREADY_LINKED", "Telegram привязан к другому аккаунту"
        ) from exc
    db.refresh(user)
    return user
