"""Напоминания о ТО — суточная задача worker'а (C-11, N-10, ADR 0019 п. 5–7).

Статус агрегата считается той же `compute_status`, что и API (ADR 0009). Вид напоминания:
красный — «просрочено» (требуется замена); остаток до порога красного ≤ N км или ≤ N дней —
«скоро замена». На цикл замены — не
больше одного каждого вида, «скоро» — только если в цикле ещё ничего не было
(`maintenance_reminder`). Агрегат без истории замен (`unknown`) напоминаний не получает.

Задача идемпотентна: повторный запуск в тот же день ничего не добавит. Один экземпляр —
advisory lock транзакции; второй экземпляр в это время пропускает запуск.
"""

import logging
from dataclasses import dataclass
from datetime import date

from sqlalchemy import BigInteger, and_, literal, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.db import constraint_name
from app.core.locks import AdvisoryLock, try_xact_lock
from app.core.time import today_in_business_tz
from app.domain.aggregates.service import get_thresholds
from app.domain.aggregates.status import (
    AggregateStatusResult,
    LeftToReplacement,
    Regulation,
    Replacement,
    Thresholds,
    TrafficLight,
    compute_status,
    left_to_replacement,
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


@dataclass(frozen=True)
class ReminderRules:
    thresholds: Thresholds
    before_km: int
    before_days: int


def reminder_kind(
    result: AggregateStatusResult, left: LeftToReplacement, rules: ReminderRules
) -> MaintenanceReminderKind | None:
    if result.status is TrafficLight.RED:
        return MaintenanceReminderKind.OVERDUE
    if result.status is TrafficLight.UNKNOWN:
        return None
    if (left.km is not None and left.km <= rules.before_km) or (
        left.days is not None and left.days <= rules.before_days
    ):
        return MaintenanceReminderKind.DUE_SOON
    return None


def reminder_message(
    model: VehicleModel,
    aggregate: AggregateType,
    kind: MaintenanceReminderKind,
    left: LeftToReplacement,
) -> str:
    head = f"{model.brand} {model.model} — {aggregate.name}"
    if kind is MaintenanceReminderKind.OVERDUE:
        return f"{head}: требуется замена. Запишитесь на ТО."
    parts = []
    if left.km is not None:
        parts.append(f"{max(left.km, 0)} км")
    if left.days is not None:
        parts.append(f"{max(left.days, 0)} дн")
    return f"{head}: до замены осталось {', '.join(parts)}. Запишитесь на ТО."


def _rules(db: Session) -> ReminderRules:
    row = get_thresholds(db)
    return ReminderRules(
        Thresholds.of(row),
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
        .where(Vehicle.is_active, *eligible_client())
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
    if not try_xact_lock(db, AdvisoryLock.MAINTENANCE_REMINDERS):
        db.rollback()
        return None
    rules = _rules(db)
    created = 0
    for vehicle, regulation, cycle, model, aggregate in _candidates(db):
        rule = Regulation(regulation.interval_km, regulation.interval_months)
        last = Replacement(cycle.last_replaced_at, cycle.last_replaced_mileage)
        result = compute_status(rule, last, vehicle.mileage, today, rules.thresholds)
        if result is None:
            continue
        left = left_to_replacement(
            rule, last, vehicle.mileage, today, rules.thresholds.red_above_percent
        )
        kind = reminder_kind(result, left, rules)
        if kind is None:
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
                    message=reminder_message(model, aggregate, kind, left),
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
