"""Управление пользователями (тег Users, Глава 17, ADR 0021 п. 3): список, сотрудники, блокировка.

Блокировка (`is_active=false`) — глоссарий «Блокировка пользователя»: отзываются все
refresh-токены и push-токены пользователя; запросы с действующим access-токеном получают 401
(`get_current_user` читает активность из БД), WebSocket закрывается при ближайшей проверке.
Тикеты заблокированного инженера остаются назначенными — переназначает администратор.

Последний активный администратор (`409 LAST_ADMIN`): изменения администраторов сериализуются
блокировкой строк всех активных администраторов — два параллельных понижения не оставят
систему без администратора.
"""

from sqlalchemy import Select, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.db import escape_like, get_by_id
from app.core.errors import ApiError
from app.core.security import hash_password
from app.domain.auth import tokens
from app.domain.auth.service import end_all_sessions
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
    """POST /users: инженер или администратор с паролем argon2id (N-08); телефон занят — 409."""
    if db.scalar(select(AppUser.id).where(AppUser.phone == phone)) is not None:
        raise _phone_taken()
    user = AppUser(phone=phone, role=role, password_hash=hash_password(password))
    db.add(user)
    try:
        db.commit()
    except IntegrityError as exc:  # параллельное создание того же номера
        db.rollback()
        raise _phone_taken() from exc
    db.refresh(user)
    return user


def _phone_taken() -> ApiError:
    return ApiError(409, "PHONE_ALREADY_REGISTERED", "Телефон уже зарегистрирован")


def create_admin(db: Session, phone: str, password: str) -> AppUser:
    """Первый администратор чистой среды (CLI `app.cli create-admin`, ADR 0021 п. 7)."""
    return create_staff_user(db, phone, UserRole.ADMIN, password)


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
    db: Session, user_id: int, role: UserRole | None, is_active: bool | None
) -> AppUser:
    """PATCH /users/{id}: роль engineer ↔ admin и блокировка/разблокировка."""
    user = get_user(db, user_id)
    admins = _lock_active_admins(db)  # до строки пользователя — общий порядок блокировок
    tokens.lock_user(db, user.id)
    db.refresh(user)

    if role is not None and role != user.role:
        if user.role not in STAFF_ROLES or role not in STAFF_ROLES:
            raise ApiError(
                409,
                "ROLE_CHANGE_NOT_ALLOWED",
                "Смена роли между клиентом и сотрудником не поддерживается",
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
        end_all_sessions(db, user.id)
    db.commit()
    db.refresh(user)
    return user
