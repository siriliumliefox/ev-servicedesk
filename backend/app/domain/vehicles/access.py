"""Object-level доступ к автомобилю (RBAC-01, RBAC_MATRIX.md, ADR 0014).

Роль из `require_roles` пускает к операции; к какому авто — решает этот модуль:
- client — свои активные авто; удалённое для него не существует;
- engineer — просмотр: авто из тикетов, назначенных на него, и из неназначенных тикетов
  в статусе `new` (очередь — карточка до «взять в работу»); изменение — только по своему
  тикету не в `resolved`. Удалённое авто по тикету видно (карточка тикета не ломается);
- admin — любое авто, в т. ч. удалённое.
Невидимое авто → 404 (не раскрываем, что id существует); видимое, но не изменяемое → 403.
"""

from enum import Enum

from sqlalchemy import and_, exists, or_, select
from sqlalchemy.orm import Session

from app.core.errors import ApiError, forbidden
from app.models import AppUser, Ticket, Vehicle
from app.models.enums import TicketStatus, UserRole

BIGINT_MAX = 2**63 - 1


class Intent(Enum):
    VIEW = "view"
    CHANGE = "change"


def not_found() -> ApiError:
    return ApiError(404, "NOT_FOUND", "Автомобиль не найден")


def _engineer_ticket(engineer_id: int, intent: Intent):
    mine = Ticket.assigned_engineer_id == engineer_id
    if intent is Intent.CHANGE:
        return and_(mine, Ticket.status != TicketStatus.RESOLVED)
    queue = and_(Ticket.assigned_engineer_id.is_(None), Ticket.status == TicketStatus.NEW)
    return or_(mine, queue)


def _engineer_can(db: Session, engineer_id: int, vehicle_id: int, intent: Intent) -> bool:
    return bool(
        db.scalar(
            select(
                exists().where(
                    Ticket.vehicle_id == vehicle_id, _engineer_ticket(engineer_id, intent)
                )
            )
        )
    )


def get_vehicle(
    db: Session, user: AppUser, vehicle_id: int, intent: Intent, *, lock: bool = False
) -> Vehicle:
    """Авто, доступное `user` для `intent`; иначе 404/403. `lock` — SELECT ... FOR UPDATE."""
    if not 1 <= vehicle_id <= BIGINT_MAX:
        raise not_found()  # вне BIGINT такого id нет; без проверки — ошибка драйвера и 500
    stmt = select(Vehicle).where(Vehicle.id == vehicle_id)
    if lock:
        stmt = stmt.with_for_update()
    vehicle = db.scalars(stmt).one_or_none()
    if vehicle is None:
        raise not_found()

    if user.role is UserRole.ADMIN:
        return vehicle
    if user.role is UserRole.CLIENT:
        if vehicle.user_id != user.id or vehicle.deleted_at is not None:
            raise not_found()
        return vehicle
    if user.role is UserRole.ENGINEER:
        if not _engineer_can(db, user.id, vehicle.id, Intent.VIEW):
            raise not_found()
        if intent is Intent.CHANGE and not _engineer_can(db, user.id, vehicle.id, intent):
            raise forbidden("Изменять авто можно только по своему тикету в работе")
        return vehicle
    raise not_found()  # неизвестная роль — deny by default


def engineer_active_ticket_id(db: Session, engineer_id: int, vehicle_id: int) -> int | None:
    """Последний созданный тикет инженера по авто не в `resolved` — для связи «тикет → ТО»."""
    return db.scalar(
        select(Ticket.id)
        .where(Ticket.vehicle_id == vehicle_id, _engineer_ticket(engineer_id, Intent.CHANGE))
        .order_by(Ticket.created_at.desc(), Ticket.id.desc())
        .limit(1)
    )
