"""Сценарии Auth Service (Глава 10): вход по SMS, вход персонала, согласие ПД, Telegram."""

import hashlib
import hmac
import logging
from dataclasses import dataclass
from datetime import UTC, datetime

from redis import Redis
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core import rate_limit
from app.core.config import Settings
from app.core.errors import ApiError, field_error, rate_limited, unauthorized
from app.core.security import hash_password, verify_password
from app.domain.auth import codes, passwords, tokens
from app.domain.auth.sms import SmsProvider, mask_phone
from app.domain.notifications.service import revoke_all_tokens as revoke_all_push_tokens
from app.models import AppUser, PdConsent
from app.models.enums import STAFF_ROLES, UserRole

logger = logging.getLogger(__name__)

STAFF_WINDOW = 15 * 60
HOUR = 3600


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
    user = db.execute(
        select(AppUser.role, AppUser.is_active).where(AppUser.phone == phone)
    ).one_or_none()
    # Соединение — обратно в пул до отправки SMS: ответ A1 ждётся секунды (ADR 0028 п. 18).
    db.commit()
    deliver = user is None or (user.role is UserRole.CLIENT and user.is_active)
    return codes.request_code(redis, sms, settings, phone, client_ip, deliver=deliver)


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


def staff_login(
    db: Session, redis: Redis, settings: Settings, phone: str, password: str, client_ip: str
) -> LoginResult:
    """POST /auth/staff/login: пароль argon2id, лимит неудачных попыток (N-06, N-08)."""
    user = _check_password(db, redis, settings, phone, password, client_ip)
    pair = tokens.issue_pair(db, user, settings)
    db.commit()
    return LoginResult(tokens=pair, user=user)


def _failure_keys(phone: str, client_ip: str) -> tuple[str, str, str]:
    """Счётчики неудач (ADR 0029 п. 11): «номер + IP», IP, номер за час."""
    return f"staff-fail:{phone}:{client_ip}", f"staff-fail-ip:{client_ip}", f"staff-fail-h:{phone}"


def clear_login_failures(redis: Redis, phone: str | None) -> None:
    """Сброс и смена пароля снимают блокировку входа номера со всех адресов."""
    if phone is None:
        return
    pattern = f"{rate_limit.PREFIX}staff-fail:{phone}:*"
    keys = list(redis.scan_iter(match=pattern, count=500))
    redis.delete(rate_limit.PREFIX + f"staff-fail-h:{phone}", *keys)


def _check_password(
    db: Session, redis: Redis, settings: Settings, phone: str, password: str, client_ip: str
) -> AppUser:
    """Доступный сотрудник с этим номером и паролем, иначе 401; лимиты неудач — 429.

    Попытка учитывается ДО проверки пароля: параллельные запросы не обходят лимит. Успешная
    проверка возвращает попытку — счётчики считают только неудачи.
    """
    pair_key, ip_key, phone_key = _failure_keys(phone, client_ip)
    # Все счётчики растут до проверки любого из них, поэтому не `rate_limit.enforce`.
    by_pair = rate_limit.hit(redis, pair_key, STAFF_WINDOW)
    by_ip = rate_limit.hit(redis, ip_key, STAFF_WINDOW)
    by_phone = rate_limit.hit(redis, phone_key, HOUR)
    if by_pair.exceeded(settings.staff_login_failures_per_phone_ip_15min):
        raise rate_limited(by_pair.retry_after, "Слишком много неудачных попыток входа")
    if by_ip.exceeded(settings.staff_login_failures_per_ip_15min):
        raise rate_limited(by_ip.retry_after, "Слишком много неудачных попыток входа")
    if by_phone.exceeded(settings.staff_login_failures_per_phone_hour):
        if by_phone.count == settings.staff_login_failures_per_phone_hour + 1:
            logger.warning("Подбор пароля сотрудника с разных адресов: %s", mask_phone(phone))
        raise rate_limited(by_phone.retry_after, "Слишком много неудачных попыток входа")

    user = db.scalars(select(AppUser).where(AppUser.phone == phone)).one_or_none()
    password_hash = user.password_hash if user is not None else None
    ok = verify_password(password, password_hash)  # считаем всегда — время не выдаёт номер
    if not ok or user is None or user.role not in STAFF_ROLES or not user.is_available:
        raise unauthorized("Неверный телефон или пароль")
    rate_limit.reset(redis, pair_key)
    rate_limit.undo_hit(redis, ip_key)
    rate_limit.undo_hit(redis, phone_key)
    return user


def end_all_sessions(db: Session, redis: Redis, settings: Settings, user_id: int) -> None:
    """Отзыв согласия и блокировка: все сессии (refresh и access) и push-токены (без COMMIT)."""
    tokens.revoke_all(db, redis, settings, user_id)
    revoke_all_push_tokens(db, user_id)


def withdraw_pd_consent(db: Session, redis: Redis, settings: Settings, user: AppUser) -> None:
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
    end_all_sessions(db, redis, settings, user.id)  # ADR 0019 п. 8
    db.commit()


def change_staff_password(
    db: Session,
    redis: Redis,
    settings: Settings,
    user: AppUser,
    current_password: str,
    new_password: str,
    client_ip: str,
) -> tokens.TokenPair:
    """POST /auth/staff/password (ADR 0029 п. 14): новая пара токенов, прочие сессии отозваны.

    Неверный текущий пароль — 400 PASSWORD_INVALID; попытка входит в лимит неудачных входов
    (п. 11), иначе смена пароля стала бы обходом лимита подбора.
    """
    try:
        _check_password(db, redis, settings, user.phone or "", current_password, client_ip)
    except ApiError as exc:
        if exc.status_code != 401:
            raise
        raise ApiError(400, "PASSWORD_INVALID", "Неверный текущий пароль") from exc
    if new_password == current_password:
        raise field_error("new_password", "VALIDATION_ERROR", "Новый пароль совпадает с текущим")
    passwords.ensure_strong(new_password, user.phone, field="new_password")
    tokens.lock_user(db, user.id)
    db.refresh(user)
    user.password_hash = hash_password(new_password)
    tokens.revoke_all(db, redis, settings, user.id)  # отметка отзыва — до выпуска новой пары
    pair = tokens.issue_pair(db, user, settings)
    db.commit()
    clear_login_failures(redis, user.phone)
    return pair


def _telegram_signature_valid(settings: Settings, fields: dict[str, str], signature: str) -> bool:
    """Подпись Telegram Login Widget: HMAC-SHA256(строка проверки, SHA-256(токен бота))."""
    check = "\n".join(f"{k}={fields[k]}" for k in sorted(fields))
    secret = hashlib.sha256(settings.telegram_bot_token.encode()).digest()
    expected = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)


def link_telegram(
    db: Session, settings: Settings, user: AppUser, widget: dict[str, str | int | None]
) -> AppUser:
    """POST /auth/telegram/link: владение аккаунтом Telegram — по подписи виджета (ADR 0029
    п. 16); один Telegram — один аккаунт. `widget` — поля запроса, `telegram_id` = `id`."""
    if not settings.telegram_bot_token:
        raise ApiError(503, "TELEGRAM_UNAVAILABLE", "Привязка Telegram временно недоступна")
    if widget.get("hash") is None or widget.get("auth_date") is None:
        raise field_error(
            "hash", "VALIDATION_ERROR", "Нужны данные Telegram Login Widget с подписью"
        )
    signature = str(widget["hash"])
    fields = {
        ("id" if k == "telegram_id" else k): str(v)
        for k, v in widget.items()
        if k != "hash" and v is not None
    }
    age = datetime.now(UTC).timestamp() - int(widget["auth_date"] or 0)
    if not _telegram_signature_valid(settings, fields, signature) or not (
        -60 <= age <= settings.telegram_auth_max_age_seconds
    ):
        raise field_error("hash", "TELEGRAM_AUTH_INVALID", "Подпись Telegram недействительна")
    telegram_id = fields["id"]
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
