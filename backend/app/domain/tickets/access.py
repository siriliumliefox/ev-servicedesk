"""Object-level доступ к тикету (RBAC-04, RBAC_MATRIX.md, ADR 0017 п. 6, 8).

Роль из `require_roles` пускает к операции; к какому тикету — решает этот модуль:
- client — тикеты своих активных авто. Удалённое авто для клиента не существует
  (`vehicles.access`), поэтому и его тикеты — тоже: смена владельца — soft-delete (ADR 0003),
  прежний владелец не продолжает диалог по проданному авто;
- engineer — очередь (`new` без исполнителя) и тикеты, назначенные ему;
- admin — любой тикет.
Невидимый тикет → 404 (не раскрываем, что id существует); видимый, но недоступный для
действия → 403. Правила записи: статус меняет назначенный инженер или admin; в чат пишут
client (свой тикет), engineer (только назначенный), admin (любой); в решённый — никто (409).
"""

from sqlalchemy import ColumnElement, and_, false, or_, select, true
from sqlalchemy.orm import Session
from sqlalchemy.sql.base import ExecutableOption

from app.core.db import is_db_id
from app.core.errors import ApiError, forbidden
from app.models import AppUser, Ticket, Vehicle
from app.models.enums import TicketStatus, UserRole


def not_found() -> ApiError:
    return ApiError(404, "NOT_FOUND", "Тикет не найден")


def ticket_resolved() -> ApiError:
    return ApiError(
        409, "TICKET_RESOLVED", "Тикет решён — сначала переоткройте его (смена статуса)"
    )


def in_queue() -> ColumnElement[bool]:
    """Условие на `Ticket`: тикет в очереди — `new` без исполнителя (ADR 0017 п. 5)."""
    return and_(Ticket.assigned_engineer_id.is_(None), Ticket.status == TicketStatus.NEW)


def visible(user: AppUser) -> ColumnElement[bool]:
    """Условие на `Ticket`: тикет виден пользователю."""
    if user.role is UserRole.ADMIN:
        return true()
    if user.role is UserRole.CLIENT:
        own = select(Vehicle.id).where(Vehicle.user_id == user.id, Vehicle.deleted_at.is_(None))
        return Ticket.vehicle_id.in_(own)
    if user.role is UserRole.ENGINEER:
        return or_(Ticket.assigned_engineer_id == user.id, in_queue())
    return false()  # неизвестная роль — deny by default


def find(
    db: Session, user: AppUser, ticket_id: int, *options: ExecutableOption, lock: bool = False
) -> Ticket | None:
    """Тикет, видимый `user`, или None. `options` — связи для ответа; lock — FOR UPDATE.

    populate_existing: claim и первичный ответ меняют строку UPDATE-ом в обход ORM — объект
    из identity map сессии не должен отдавать прежнее состояние.
    """
    if not is_db_id(ticket_id):
        return None
    stmt = (
        select(Ticket)
        .where(Ticket.id == ticket_id, visible(user))
        .options(*options)
        .execution_options(populate_existing=True)
    )
    if lock:
        stmt = stmt.with_for_update(of=Ticket)
    return db.scalars(stmt).one_or_none()


def get_ticket(db: Session, user: AppUser, ticket_id: int, *options: ExecutableOption) -> Ticket:
    """Тикет, видимый `user`, иначе 404. `options` — загрузка связей для ответа."""
    ticket = find(db, user, ticket_id, *options)
    if ticket is None:
        raise not_found()
    return ticket


def for_update(db: Session, user: AppUser, ticket_id: int) -> Ticket:
    """Видимый тикет под SELECT ... FOR UPDATE (смена статуса, назначение, сообщение), иначе 404.

    Блокировка упорядочивает сообщения со сменой статуса: «решён» не проскочит между
    проверкой и вставкой сообщения.
    """
    ticket = find(db, user, ticket_id, lock=True)
    if ticket is None:
        raise not_found()
    return ticket


def is_visible(db: Session, user: AppUser, ticket_id: int) -> bool:
    """Для WebSocket: доступ при подключении и повторная проверка на каждом событии."""
    if not is_db_id(ticket_id):
        return False
    return db.scalar(select(Ticket.id).where(Ticket.id == ticket_id, visible(user))) is not None


def ensure_can_change_status(user: AppUser, ticket: Ticket) -> None:
    """Статус меняет назначенный инженер или admin; тикет из очереди инженеру — 403."""
    if user.role is UserRole.ENGINEER and ticket.assigned_engineer_id != user.id:
        raise forbidden("Статус меняет назначенный инженер — сначала возьмите тикет в работу")


def ensure_can_write_message(user: AppUser, ticket: Ticket) -> None:
    """Инженер пишет только в назначенный тикет (очередь — сначала claim); в решённый — никто."""
    if user.role is UserRole.ENGINEER and ticket.assigned_engineer_id != user.id:
        raise forbidden("Писать в чат можно после того, как тикет взят в работу")
    if ticket.status is TicketStatus.RESOLVED:
        raise ticket_resolved()


def hides_staff_contacts(viewer: AppUser, author: AppUser) -> bool:
    """Клиенту телефон и Telegram сотрудника не отдаются (ADR 0017 п. 12, минимизация ПД)."""
    return viewer.role is UserRole.CLIENT and author.role is not UserRole.CLIENT


def active_user(db: Session, user_id: int) -> AppUser | None:
    """Пользователь токена — как в `get_current_user`: роль и активность из БД."""
    user = db.get(AppUser, user_id, populate_existing=True)
    return user if user is not None and user.is_available else None
