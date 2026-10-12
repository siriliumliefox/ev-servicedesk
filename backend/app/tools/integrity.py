"""Аудит целостности данных между модулями (Глава 17, ADR 0021 п. 8).

`python -m app.tools.integrity` — именованные проверки инвариантов, которые не выражены
ограничениями БД, потому что связывают таблицы разных модулей (Auth, Vehicle, Aggregates,
Tickets, Notifications). Правила берутся из канонических определений домена
(`AppUser.is_available`, `notifications.service.eligible_client`), а не переписываются заново.
Печатает только имена проверок, число нарушений и id строк — без ПД. Код выхода 1 — есть
нарушения. Запускается в тестах, на стеке после сквозного сценария и в мониторинге (главы 26,
28). Только чтение.
"""

import sys
from dataclasses import dataclass

from sqlalchemy import ColumnElement, Select, exists, func, not_, or_, select
from sqlalchemy.orm import Session, aliased

from app.core.db import get_session_scope
from app.domain.notifications.service import eligible_client
from app.models import (
    AppUser,
    MaintenanceRecord,
    MaintenanceReminder,
    Notification,
    NotificationDelivery,
    NotificationRecipient,
    PushToken,
    RefreshToken,
    Ticket,
    TicketMessage,
    Vehicle,
    VehicleAggregateStatus,
)
from app.models.enums import NotificationType, UserRole

SAMPLE = 10  # id нарушений в отчёте — не больше


@dataclass(frozen=True)
class Check:
    name: str
    description: str
    violations: Select[tuple[int]]  # id нарушающих строк


def _is_client(user_id: ColumnElement[int | None]) -> ColumnElement[bool]:
    return exists().where(AppUser.id == user_id, AppUser.role == UserRole.CLIENT)


def _replacement_without_history() -> Select[tuple[int]]:
    status = VehicleAggregateStatus
    record = (
        select(MaintenanceRecord.id)
        .where(
            MaintenanceRecord.vehicle_id == status.vehicle_id,
            MaintenanceRecord.aggregate_type_id == status.aggregate_type_id,
            MaintenanceRecord.performed_at == status.last_replaced_at,
            MaintenanceRecord.mileage_at_service.is_not_distinct_from(status.last_replaced_mileage),
        )
        .exists()
    )
    return select(status.id).where(status.last_replaced_at.is_not(None), not_(record))


def _active_push_token_of_ineligible_user() -> Select[tuple[int]]:
    eligible = exists().where(AppUser.id == PushToken.user_id, *eligible_client())
    return select(PushToken.id).where(PushToken.revoked_at.is_(None), not_(eligible))


def _reminder_notification_mismatch() -> Select[tuple[int]]:
    reminder = MaintenanceReminder
    return (
        select(reminder.id)
        .join(Notification, Notification.id == reminder.notification_id)
        .where(
            or_(
                Notification.type != NotificationType.MAINTENANCE,
                Notification.vehicle_id.is_distinct_from(reminder.vehicle_id),
                Notification.aggregate_type_id.is_distinct_from(reminder.aggregate_type_id),
            )
        )
    )


def _delivery_to_non_recipient() -> Select[tuple[int]]:
    recipient = exists().where(
        NotificationRecipient.notification_id == NotificationDelivery.notification_id,
        NotificationRecipient.user_id == PushToken.user_id,
    )
    return (
        select(NotificationDelivery.id)
        .join(PushToken, PushToken.id == NotificationDelivery.push_token_id)
        .where(not_(recipient))
    )


author = aliased(AppUser)

CHECKS: tuple[Check, ...] = (
    Check(
        "replacement_without_history",
        "Последняя замена агрегата без записи в истории ТО (замена пишет оба, ADR 0016)",
        _replacement_without_history(),
    ),
    Check(
        "maintenance_record_of_other_vehicle_ticket",
        "Работа ТО привязана к тикету другого авто",
        select(MaintenanceRecord.id)
        .join(Ticket, Ticket.id == MaintenanceRecord.ticket_id)
        .where(Ticket.vehicle_id != MaintenanceRecord.vehicle_id),
    ),
    Check(
        "maintenance_record_by_client",
        "Работу ТО записал клиент (только инженер или администратор)",
        select(MaintenanceRecord.id).where(_is_client(MaintenanceRecord.performed_by_user_id)),
    ),
    Check(
        "vehicle_owner_not_client",
        "Владелец авто — не клиент",
        select(Vehicle.id).where(not_(_is_client(Vehicle.user_id))),
    ),
    Check(
        "ticket_assignee_is_client",
        "Исполнитель тикета — клиент",
        select(Ticket.id).where(_is_client(Ticket.assigned_engineer_id)),
    ),
    Check(
        "ticket_created_for_deleted_vehicle",
        "Тикет создан после удаления авто",
        select(Ticket.id)
        .join(Vehicle, Vehicle.id == Ticket.vehicle_id)
        .where(Ticket.created_at > Vehicle.deleted_at),
    ),
    Check(
        "client_message_in_foreign_ticket",
        "Клиент написал в тикет чужого авто",
        select(TicketMessage.id)
        .join(author, author.id == TicketMessage.author_id)
        .join(Ticket, Ticket.id == TicketMessage.ticket_id)
        .join(Vehicle, Vehicle.id == Ticket.vehicle_id)
        .where(author.role == UserRole.CLIENT, Vehicle.user_id != TicketMessage.author_id),
    ),
    Check(
        "active_refresh_token_of_unavailable_user",
        "Действующий refresh-токен у заблокированного или анонимизированного",
        select(RefreshToken.id)
        .join(AppUser, AppUser.id == RefreshToken.user_id)
        .where(
            RefreshToken.revoked_at.is_(None),
            RefreshToken.expires_at > func.now(),
            not_(AppUser.is_available),
        ),
    ),
    Check(
        "active_push_token_of_ineligible_user",
        "Активный push-токен у пользователя, которому уведомления не положены",
        _active_push_token_of_ineligible_user(),
    ),
    Check(
        "notification_recipient_not_client",
        "Получатель уведомления — не клиент",
        select(NotificationRecipient.id).where(not_(_is_client(NotificationRecipient.user_id))),
    ),
    Check(
        "vehicle_notification_to_non_owner",
        "Уведомление об авто (напоминание о ТО) получил не владелец авто",
        select(NotificationRecipient.id)
        .join(Notification, Notification.id == NotificationRecipient.notification_id)
        .join(Vehicle, Vehicle.id == Notification.vehicle_id)
        .where(NotificationRecipient.user_id != Vehicle.user_id),
    ),
    Check(
        "reminder_notification_mismatch",
        "Напоминание о ТО не совпадает со своим уведомлением (тип, авто, агрегат)",
        _reminder_notification_mismatch(),
    ),
    Check(
        "reminder_for_deleted_vehicle",
        "Напоминание о ТО создано после удаления авто",
        select(MaintenanceReminder.id)
        .join(Vehicle, Vehicle.id == MaintenanceReminder.vehicle_id)
        .where(MaintenanceReminder.created_at > Vehicle.deleted_at),
    ),
    Check(
        "delivery_to_non_recipient",
        "Доставка push на устройство пользователя, не входящего в получатели уведомления",
        _delivery_to_non_recipient(),
    ),
)


@dataclass(frozen=True)
class Violation:
    check: Check
    count: int
    sample: list[int]


def run_checks(db: Session) -> list[Violation]:
    """Нарушения по всем проверкам (пустой список — данные согласованы)."""
    violations = []
    for check in CHECKS:
        stmt = check.violations
        ids = list(db.scalars(stmt.order_by(stmt.selected_columns[0])))
        if ids:
            violations.append(Violation(check, len(ids), ids[:SAMPLE]))
    return violations


def main() -> int:
    with get_session_scope()() as db:
        violations = run_checks(db)
    failed = {v.check.name: v for v in violations}
    for check in CHECKS:
        v = failed.get(check.name)
        if v is None:
            print(f"PASS  {check.name}")
        else:
            ids = ", ".join(map(str, v.sample))
            print(f"FAIL  {check.name}: {v.count} — {check.description} (id: {ids})")
    print(f"Проверок: {len(CHECKS)}, с нарушениями: {len(violations)}")
    return 1 if violations else 0


if __name__ == "__main__":
    sys.exit(main())
