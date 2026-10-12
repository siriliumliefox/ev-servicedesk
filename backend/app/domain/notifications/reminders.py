"""Напоминания о ТО — суточная задача worker'а (C-11, N-10, ADR 0019 п. 5–7).

Статус агрегата считается той же `compute_status`, что и API (ADR 0009). Вид напоминания:
красный — «просрочено»; остаток ≤ N км или ≤ N дней — «скоро замена». На цикл замены — не
больше одного каждого вида, «скоро» — только если в цикле ещё ничего не было
(`maintenance_reminder`). Агрегат без истории замен (`unknown`) напоминаний не получает.

Задача идемпотентна: повторный запуск в тот же день ничего не добавит. Один экземпляр —
advisory lock транзакции; второй экземпляр в это время пропускает запуск.
"""

import logging
from dataclasses import dataclass
from datetime import date

from sqlalchemy import BigInteger, and_, literal, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.db import constraint_name
from app.domain.aggregates.service import get_thresholds, today_in_business_tz
from app.domain.aggregates.status import (
    AggregateStatusResult,
    Regulation,
    Replacement,
    Thresholds,
    TrafficLight,
    compute_status,
)
from app.domain.notifications.outbox import Outbox
from app.domain.notifications.service import eligible_client, enqueue
from app.models import (
    AggregateType,
    AppUser,
    MaintenanceRegulation,
    MaintenanceReminder,
    Notification,
    Vehicle,
    VehicleAggregateStatus,
    VehicleModel,
)
from app.models.enums import MaintenanceReminderKind, NotificationType

logger = logging.getLogger(__name__)

ADVISORY_LOCK_KEY = 15_0019  # глава 15, ADR 0019


@dataclass(frozen=True)
class ReminderRules:
    thresholds: Thresholds
    before_km: int
    before_days: int


def reminder_kind(
    result: AggregateStatusResult, rules: ReminderRules
) -> MaintenanceReminderKind | None:
    if result.status is TrafficLight.RED:
        return MaintenanceReminderKind.OVERDUE
    if result.status is TrafficLight.UNKNOWN:
        return None
    if (result.remaining_km is not None and result.remaining_km <= rules.before_km) or (
        result.remaining_days is not None and result.remaining_days <= rules.before_days
    ):
        return MaintenanceReminderKind.DUE_SOON
    return None


def reminder_message(
    model: VehicleModel,
    aggregate: AggregateType,
    kind: MaintenanceReminderKind,
    result: AggregateStatusResult,
) -> str:
    head = f"{model.brand} {model.model} — {aggregate.name}"
    if kind is MaintenanceReminderKind.OVERDUE:
        return f"{head}: срок замены прошёл. Запишитесь на ТО."
    left = []
    if result.remaining_km is not None:
        left.append(f"{result.remaining_km} км")
    if result.remaining_days is not None:
        left.append(f"{result.remaining_days} дн")
    return f"{head}: до замены осталось {', '.join(left)}. Запишитесь на ТО."


def _rules(db: Session) -> ReminderRules:
    row = get_thresholds(db)
    return ReminderRules(
        Thresholds(row.yellow_from_percent, row.red_above_percent),
        row.reminder_before_km,
        row.reminder_before_days,
    )


def _candidates(db: Session):  # noqa: ANN202 — строки Result из пяти сущностей
    """Отслеживаемые агрегаты неудалённых авто клиентов, которым можно слать уведомления."""
    return db.execute(
        select(Vehicle, MaintenanceRegulation, VehicleAggregateStatus, VehicleModel, AggregateType)
        .join(AppUser, AppUser.id == Vehicle.user_id)
        .join(VehicleModel, VehicleModel.id == Vehicle.vehicle_model_id)
        .join(
            MaintenanceRegulation,
            and_(
                MaintenanceRegulation.vehicle_model_id == Vehicle.vehicle_model_id,
                MaintenanceRegulation.is_archived.is_(False),
            ),
        )
        .join(AggregateType, AggregateType.id == MaintenanceRegulation.aggregate_type_id)
        .join(
            VehicleAggregateStatus,
            and_(
                VehicleAggregateStatus.vehicle_id == Vehicle.id,
                VehicleAggregateStatus.aggregate_type_id == MaintenanceRegulation.aggregate_type_id,
            ),
        )
        .where(Vehicle.deleted_at.is_(None), *eligible_client())
        .order_by(Vehicle.id, MaintenanceRegulation.aggregate_type_id)
    ).all()


def _sent_kinds(
    db: Session, vehicle_id: int, aggregate_type_id: int, cycle: VehicleAggregateStatus
) -> set[MaintenanceReminderKind]:
    return set(
        db.scalars(
            select(MaintenanceReminder.kind).where(
                MaintenanceReminder.vehicle_id == vehicle_id,
                MaintenanceReminder.aggregate_type_id == aggregate_type_id,
                MaintenanceReminder.cycle_replaced_at.is_not_distinct_from(cycle.last_replaced_at),
                MaintenanceReminder.cycle_replaced_mileage.is_not_distinct_from(
                    cycle.last_replaced_mileage
                ),
            )
        )
    )


def run_maintenance_reminders(db: Session, outbox: Outbox, today: date | None = None) -> int | None:
    """Создаёт положенные напоминания; None — задачу сейчас выполняет другой экземпляр."""
    today = today or today_in_business_tz()
    locked = db.execute(
        text("SELECT pg_try_advisory_xact_lock(:k)"), {"k": ADVISORY_LOCK_KEY}
    ).scalar_one()
    if not locked:
        db.rollback()
        return None
    rules = _rules(db)
    created = 0
    for vehicle, regulation, cycle, model, aggregate in _candidates(db):
        result = compute_status(
            Regulation(regulation.interval_km, regulation.interval_months),
            Replacement(cycle.last_replaced_at, cycle.last_replaced_mileage),
            vehicle.mileage,
            today,
            rules.thresholds,
        )
        kind = None if result is None else reminder_kind(result, rules)
        if result is None or kind is None:
            continue
        sent = _sent_kinds(db, vehicle.id, aggregate.id, cycle)
        if kind in sent or (kind is MaintenanceReminderKind.DUE_SOON and sent):
            continue
        try:
            with db.begin_nested():
                notification = Notification(
                    type=NotificationType.MAINTENANCE,
                    target_vehicle_model_id=model.id,
                    vehicle_id=vehicle.id,
                    aggregate_type_id=aggregate.id,
                    message=reminder_message(model, aggregate, kind, result),
                )
                db.add(notification)
                db.flush()
                db.add(
                    MaintenanceReminder(
                        vehicle_id=vehicle.id,
                        aggregate_type_id=aggregate.id,
                        kind=kind,
                        cycle_replaced_at=cycle.last_replaced_at,
                        cycle_replaced_mileage=cycle.last_replaced_mileage,
                        notification_id=notification.id,
                    )
                )
                db.flush()
                enqueue(db, notification, select(literal(vehicle.user_id, BigInteger).label("id")))
        except IntegrityError as exc:
            if constraint_name(exc) != "uq_maintenance_reminder_cycle":
                raise
            continue
        created += 1
    db.commit()
    if created:
        outbox.wake()
    logger.info("Напоминаний о ТО создано: %d", created)
    return created
