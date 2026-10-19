"""Object-level доступ к автомобилю (RBAC-01, RBAC_MATRIX.md, ADR 0014).

Роль из `require_roles` пускает к операции; к какому авто — решает этот модуль:
- client — свои активные авто; удалённое для него не существует;
- engineer — просмотр: авто из тикетов, назначенных на него, и из неназначенных тикетов
  в статусе `new` (очередь — карточка до «взять в работу»); изменение — только по своему
  тикету не в `resolved`. Удалённое авто по тикету видно (карточка тикета не ломается);
- admin — любое авто, в т. ч. удалённое.
Изменение ⊂ просмотр; удалённое авто не изменяется никем. Невидимое авто → 404 (не
раскрываем, что id существует); видимое, но не изменяемое → 403.
"""

from typing import NamedTuple

from sqlalchemy import ColumnElement, ScalarSelect, exists, false, null, select, true
from sqlalchemy.orm import Session
from sqlalchemy.sql.base import ExecutableOption

from app.core.db import is_db_id
from app.core.errors import ApiError, forbidden
from app.domain.tickets import access as ticket_access
from app.models import AppUser, Ticket, Vehicle
from app.models.enums import TicketStatus, UserRole


class Change(NamedTuple):
    """Авто, заблокированное для изменения, и тикет-основание (у инженера; иначе None)."""

    vehicle: Vehicle
    ticket_id: int | None


def not_found() -> ApiError:
    return ApiError(404, "NOT_FOUND", "Автомобиль не найден")


def _check_id(vehicle_id: int) -> None:
    if not is_db_id(vehicle_id):
        raise not_found()  # вне BIGINT такого id нет; без проверки — ошибка драйвера и 500


def _visible(user: AppUser) -> ColumnElement[bool]:
    """Условие на `Vehicle`: авто видно пользователю."""
    if user.role is UserRole.ADMIN:
        return true()
    if user.role is UserRole.CLIENT:
        return Vehicle.owned_active(user.id)
    if user.role is UserRole.ENGINEER:
        # Авто, по которому есть видимый инженеру тикет: свой или из очереди.
        return exists().where(Ticket.vehicle_id == Vehicle.id, ticket_access.visible(user))
    return false()  # неизвестная роль — deny by default


def _active_ticket_id(engineer_id: int) -> ScalarSelect[int]:
    """Последний созданный тикет инженера по авто не в `resolved` — связь «тикет → ТО»."""
    return (
        select(Ticket.id)
        .where(
            Ticket.vehicle_id == Vehicle.id,
            Ticket.assigned_engineer_id == engineer_id,
            Ticket.status != TicketStatus.RESOLVED,
        )
        .order_by(Ticket.created_at.desc(), Ticket.id.desc())
        .limit(1)
        .correlate(Vehicle)
        .scalar_subquery()
    )


def _change_basis(user: AppUser) -> tuple[ColumnElement[bool], ColumnElement[int | None]]:
    """(право изменить видимое авто, тикет-основание): у инженера — свой тикет в работе."""
    if user.role is UserRole.ENGINEER:
        ticket = _active_ticket_id(user.id)
        return ticket.is_not(None), ticket
    return true(), null()


def get_vehicle(db: Session, user: AppUser, vehicle_id: int, *options: ExecutableOption) -> Vehicle:
    """Авто, видимое `user`, иначе 404. `options` — загрузка связей для ответа."""
    _check_id(vehicle_id)
    vehicle = db.scalars(
        select(Vehicle).where(Vehicle.id == vehicle_id, _visible(user)).options(*options)
    ).one_or_none()
    if vehicle is None:
        raise not_found()
    return vehicle


def for_new_ticket(db: Session, user: AppUser, vehicle_id: int) -> Vehicle:
    """Активное видимое авто под SELECT ... FOR SHARE — запись нового тикета, иначе 404.

    Тикет создаётся только на активное авто (ADR 0017 п. 6): удаление и передача авто
    (soft-delete под FOR NO KEY UPDATE, ADR 0003) ждут commit тикета, а создание, дождавшись
    удаления, видит deleted_at — 404.
    """
    _check_id(vehicle_id)
    vehicle = db.scalars(
        select(Vehicle)
        .where(Vehicle.id == vehicle_id, Vehicle.is_active, _visible(user))
        .with_for_update(read=True, of=Vehicle)
        .execution_options(populate_existing=True)
    ).one_or_none()
    if vehicle is None:
        raise not_found()
    return vehicle


def for_change(db: Session, user: AppUser, vehicle_id: int) -> Change:
    """Авто под SELECT ... FOR NO KEY UPDATE, которое `user` может изменить, иначе 404/403.

    Изменения авто (пробег, прошивка, замена агрегата, мягкое удаление) не трогают ключ, поэтому
    FOR NO KEY UPDATE: изменения по-прежнему идут по очереди и ждут создание тикета (FOR SHARE),
    но не ждут чужие вставки со ссылкой на авто (FK берёт FOR KEY SHARE до конца транзакции) —
    например, суточные напоминания о ТО одной транзакцией (глава 24, прогон k6: пробег ждал до
    минуты). Успешный путь — один запрос; 404 и 403 различаются только при отказе.
    """
    _check_id(vehicle_id)
    allowed, ticket_id = _change_basis(user)
    row = db.execute(
        select(Vehicle, ticket_id)
        .where(Vehicle.id == vehicle_id, Vehicle.is_active, _visible(user), allowed)
        .with_for_update(of=Vehicle, key_share=True)
    ).one_or_none()
    if row is None:
        raise _change_denied(db, user, vehicle_id)
    return Change(row[0], row[1])


def _change_denied(db: Session, user: AppUser, vehicle_id: int) -> ApiError:
    visible = db.execute(
        select(Vehicle.deleted_at).where(Vehicle.id == vehicle_id, _visible(user))
    ).one_or_none()
    if visible is None:
        return not_found()
    if visible.deleted_at is not None:
        return forbidden("Автомобиль удалён — изменения недоступны")
    return forbidden("Изменять авто можно только по своему тикету в работе")
