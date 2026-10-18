"""Управление пользователями (тег Users, Глава 17, ADR 0021 п. 3): список, сотрудники, блокировка.

Сброс пароля сотрудника (ADR 0026 п. 5) — глоссарий «Учётная запись сотрудника».

Блокировка (`is_active=false`) — глоссарий «Блокировка пользователя»: отзываются все
refresh-токены и push-токены пользователя; запросы с действующим access-токеном получают 401
(`get_current_user` читает активность из БД), WebSocket закрывается при ближайшей проверке.
Тикеты заблокированного инженера остаются назначенными — переназначает администратор.

Последний активный администратор (`409 LAST_ADMIN`): изменения администраторов сериализуются
блокировкой строк всех активных администраторов — два параллельных понижения не оставят
систему без администратора.
"""

from redis import Redis
from sqlalchemy import Select, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.db import constraint_name, escape_like, get_by_id
from app.core.errors import ApiError
from app.core.security import hash_password
from app.domain.auth import passwords, tokens
from app.domain.auth.service import clear_login_failures, end_all_sessions
from app.models import AppUser
from app.models.enums import STAFF_ROLES, UserRole


def _not_found() -> ApiError:
    return ApiError(404, "USER_NOT_FOUND", "Пользователь не найден")


def list_users_stmt(
    role: UserRole | None, is_active: bool | None, search: str | None
) -> Select[tuple[AppUser]]:
    """GET /users: фильтры по роли, активности и подстроке телефона; анонимизированные — тоже."""
    stmt = select(AppUser).order_by(AppUser.id)
    if role is not None:
        stmt = stmt.where(AppUser.role == role)
    if is_active is not None:
        stmt = stmt.where(AppUser.is_active.is_(is_active))
    if search and search.strip():
        stmt = stmt.where(AppUser.phone.like(f"%{escape_like(search.strip())}%", escape="\\"))
    return stmt


def get_user(db: Session, user_id: int) -> AppUser:
    user = get_by_id(db, AppUser, user_id)
    if user is None:
        raise _not_found()
    return user


def create_staff_user(db: Session, phone: str, role: UserRole, password: str) -> AppUser:
    """POST /users и CLI первого администратора: сотрудник с паролем argon2id (N-08).

    Телефон занят (клиентом или сотрудником, в том числе параллельным запросом) — 409:
    решает UNIQUE телефона, без предварительного поиска. Слабый пароль — 422 (ADR 0029 п. 13).
    """
    passwords.ensure_strong(password, phone)
    user = AppUser(phone=phone, role=role, password_hash=hash_password(password))
    db.add(user)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        if constraint_name(exc) != "uq_app_user_phone":
            raise
        raise ApiError(409, "PHONE_ALREADY_REGISTERED", "Телефон уже зарегистрирован") from exc
    db.refresh(user)
    return user


def _lock_active_admins(db: Session) -> list[int]:
    return list(
        db.scalars(
            select(AppUser.id)
            .where(AppUser.role == UserRole.ADMIN, AppUser.is_active.is_(True))
            .order_by(AppUser.id)
            .with_for_update()
        )
    )


def update_user(
    db: Session,
    redis: Redis,
    settings: Settings,
    user_id: int,
    role: UserRole | None,
    is_active: bool | None,
) -> AppUser:
    """PATCH /users/{id}: роль engineer ↔ admin и блокировка/разблокировка."""
    user = get_user(db, user_id)
    admins = _lock_active_admins(db)  # до строки пользователя — общий порядок блокировок
    tokens.lock_user(db, user.id)
    db.refresh(user)

    # Схема запроса допускает только роли персонала: менять роль нельзя лишь клиенту.
    if role is not None and role != user.role and user.role not in STAFF_ROLES:
        raise ApiError(
            409,
            "ROLE_CHANGE_NOT_ALLOWED",
            "Смена роли клиента на роль сотрудника не поддерживается",
        )
    new_role = role if role is not None else user.role
    new_active = is_active if is_active is not None else user.is_active

    stays_admin = new_role == UserRole.ADMIN and new_active
    if user.id in admins and not stays_admin and len(admins) == 1:
        raise ApiError(
            409, "LAST_ADMIN", "Нельзя понизить или заблокировать последнего администратора"
        )

    blocking = user.is_active and not new_active
    user.role = new_role
    user.is_active = new_active
    if blocking:
        end_all_sessions(db, redis, settings, user.id)
    db.commit()
    db.refresh(user)
    return user


def reset_password(
    db: Session, redis: Redis, settings: Settings, user_id: int, password: str
) -> None:
    """POST /users/{id}/password: новый пароль сотрудника; все его сессии (refresh и access)
    отзываются, счётчики неудачных входов номера сбрасываются (ADR 0029 пп. 11–12).

    Анонимизированный — 404 (данных пользователя нет); клиент — 409 (пароля у него нет).
    Push-токены не трогаем: они только у клиентов.
    """
    user = get_user(db, user_id)
    tokens.lock_user(db, user.id)
    db.refresh(user)
    if user.anonymized_at is not None:
        raise _not_found()
    if user.role not in STAFF_ROLES:
        raise ApiError(409, "PASSWORD_NOT_ALLOWED", "У клиента нет пароля: вход по SMS-коду")
    passwords.ensure_strong(password, user.phone)
    user.password_hash = hash_password(password)
    tokens.revoke_all(db, redis, settings, user.id)
    db.commit()
    clear_login_failures(redis, user.phone)
