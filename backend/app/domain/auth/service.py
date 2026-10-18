"""Сценарии Auth Service (Глава 10): вход по SMS, согласие ПД, Telegram. Вход и пароль
сотрудника — `staff.py`, подпись Telegram — `telegram.py`."""

import logging
from dataclasses import dataclass
from datetime import UTC, datetime

from redis import Redis
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core import rate_limit
from app.core.config import Settings
from app.core.errors import ApiError
from app.domain.auth import codes, tokens
from app.domain.auth.sms import SmsProvider
from app.domain.notifications.service import revoke_all_tokens as revoke_all_push_tokens
from app.models import AppUser, PdConsent
from app.models.enums import STAFF_ROLES, UserRole

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class LoginResult:
    tokens: tokens.TokenPair
    user: AppUser
    is_new_user: bool = False


def _active_consent(db: Session, user_id: int) -> PdConsent | None:
    return db.scalars(
        select(PdConsent).where(PdConsent.user_id == user_id, PdConsent.withdrawn_at.is_(None))
    ).one_or_none()


def request_phone_code(
    db: Session,
    redis: Redis,
    sms: SmsProvider,
    settings: Settings,
    phone: str,
    client_ip: str,
) -> int:
    """POST /auth/phone/request-code: код входа; заблокированному и сотруднику — без SMS (#103)."""
    request = codes.reserve(redis, settings, phone, client_ip)  # 429 — до запроса к БД
    user = db.execute(
        select(AppUser.role, AppUser.is_active).where(AppUser.phone == phone)
    ).one_or_none()
    # Соединение — обратно в пул до отправки SMS: ответ A1 ждётся секунды (ADR 0028 п. 18).
    db.commit()
    if user is not None and not (user.role is UserRole.CLIENT and user.is_active):
        # Тот же ответ без кода и SMS: не раскрывает, чей номер; платное SMS не тратится.
        logger.info("Код входа не отправлен: номер недоступен для входа по SMS")
        return settings.sms_code_ttl_seconds
    return codes.send(redis, sms, settings, phone, request)


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
        if not user.is_available:  # заблокирован или анонимизирован (ревью главы 17)
            raise ApiError(400, "ACCOUNT_DISABLED", "Вход заблокирован администратором")

    if user is not None:
        # Сериализация с DELETE /auth/pd-consent: согласие читается под блокировкой пользователя.
        tokens.lock_user(db, user.id)
    consent = _active_consent(db, user.id) if user is not None else None
    if consent is None and not pd_policy_version:
        # Код не расходуется: клиент повторит запрос с согласием (99-З, ст. 5).
        raise ApiError(
            422,
            "PD_CONSENT_REQUIRED",
            "Требуется согласие на обработку персональных данных",
        )

    if not codes.consume_code(redis, phone, result.code_hash):
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
            tokens.lock_user(db, user.id)
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


def end_all_sessions(db: Session, user_id: int) -> None:
    """Отзыв согласия и блокировка: все сессии (refresh и access) и push-токены (без COMMIT)."""
    tokens.revoke_all(db, user_id)
    revoke_all_push_tokens(db, user_id)


def withdraw_pd_consent(db: Session, user: AppUser) -> None:
    """DELETE /auth/pd-consent (99-З, ст. 10): отзыв + завершение всех сессий и push-токенов.

    Очередь анонимизации (≤ 15 дней, глава 25) — пользователи БЕЗ действующего согласия,
    по последнему withdrawn_at: строка с withdrawn_at бывает и у согласия, заменённого
    новой редакцией (ADR 0013, п. 9).
    """
    tokens.lock_user(db, user.id)
    consent = db.scalars(
        select(PdConsent)
        .where(PdConsent.user_id == user.id, PdConsent.withdrawn_at.is_(None))
        .with_for_update()
    ).one_or_none()
    if consent is None:
        raise ApiError(409, "PD_CONSENT_NOT_ACTIVE", "Действующего согласия нет")
    consent.withdrawn_at = datetime.now(UTC)
    end_all_sessions(db, user.id)  # ADR 0019 п. 8
    db.commit()


def link_telegram(db: Session, user: AppUser, telegram_id: str) -> AppUser:
    """POST /auth/telegram/link: один Telegram — один аккаунт; владение проверяет
    `telegram.verify_widget` (ADR 0029 п. 16)."""
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
