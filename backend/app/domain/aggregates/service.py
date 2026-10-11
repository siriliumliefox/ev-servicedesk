"""Сценарии Aggregates & Maintenance Service (Глава 12, ADR 0009, ADR 0016).

Статус «светофор» не хранится: сервис загружает входы (регламент, последняя замена, пробег,
пороги) и вызывает чистую `compute_status`. Доступ к авто — `vehicles.access` (ADR 0014 п. 4).
`today` — параметр со значением по умолчанию «сегодня по Europe/Minsk»: тесты сценариев
главы 5 передают дату из YAML.
"""

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Select, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from app.core.db import constraint_name
from app.core.errors import ApiError
from app.core.time import BUSINESS_TZ
from app.domain.aggregates.status import (
    Regulation,
    Replacement,
    Thresholds,
    TrafficLight,
    becomes_current,
    compute_status,
)
from app.domain.vehicles import access
from app.models import (
    AggregateStatusThresholds,
    AggregateType,
    AppUser,
    MaintenanceRecord,
    MaintenanceRegulation,
    Vehicle,
    VehicleAggregateStatus,
    VehicleModel,
)

REGULATION_OUT = (selectinload(MaintenanceRegulation.aggregate_type),)
THRESHOLDS_ID = 1  # одна строка, seed — миграция 0005 (ADR 0009)


def today_in_business_tz() -> date:
    return datetime.now(BUSINESS_TZ).date()


def _field_error(field: str, code: str, message: str) -> ApiError:
    return ApiError(422, code, message, details={"fields": [{"loc": ["body", field]}]})


# ---------- Справочник агрегатов ----------


def list_aggregate_types_stmt() -> Select:
    return select(AggregateType).order_by(AggregateType.id)


def create_aggregate_type(db: Session, code: str, name: str) -> AggregateType:
    """POST /aggregate-types (admin): повтор кода — 409, в т. ч. в гонке (UNIQUE)."""
    aggregate_type = AggregateType(code=code, name=name)
    db.add(aggregate_type)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        if constraint_name(exc) != "uq_aggregate_type_code":
            raise
        raise ApiError(409, "AGGREGATE_TYPE_EXISTS", "Агрегат с таким кодом уже есть") from exc
    db.commit()
    return aggregate_type


# ---------- Регламенты ТО ----------


def list_regulations_stmt(vehicle_model_id: int | None, include_archived: bool) -> Select:
    stmt = (
        select(MaintenanceRegulation)
        .order_by(
            MaintenanceRegulation.vehicle_model_id,
            MaintenanceRegulation.aggregate_type_id,
            MaintenanceRegulation.id.desc(),  # новые версии первыми
        )
        .options(*REGULATION_OUT)
    )
    if vehicle_model_id is not None:
        stmt = stmt.where(MaintenanceRegulation.vehicle_model_id == vehicle_model_id)
    if not include_archived:
        stmt = stmt.where(MaintenanceRegulation.is_archived.is_(False))
    return stmt


def _aggregate_type_id(db: Session, code: str) -> int | None:
    return db.scalar(select(AggregateType.id).where(AggregateType.code == code))


def revise_regulation(
    db: Session,
    vehicle_model_id: int,
    aggregate_type_code: str,
    interval_km: int | None,
    interval_months: int | None,
) -> MaintenanceRegulation:
    """POST /maintenance-regulations (admin): активная версия архивируется, создаётся новая.

    Пересмотры одной модели идут по очереди: строка модели блокируется FOR NO KEY UPDATE
    (не мешает FK-проверкам при добавлении авто этой модели). Так оба одновременных запроса
    получают 201, побеждает последний, а `uq_maintenance_regulation_active` не нарушается.
    """
    model_id = db.scalar(
        select(VehicleModel.id)
        .where(VehicleModel.id == vehicle_model_id)
        .with_for_update(key_share=True)
    )
    if model_id is None:
        raise _field_error("vehicle_model_id", "VEHICLE_MODEL_NOT_FOUND", "Модель не найдена")
    aggregate_type_id = _aggregate_type_id(db, aggregate_type_code)
    if aggregate_type_id is None:
        raise _field_error(
            "aggregate_type_code", "AGGREGATE_TYPE_NOT_FOUND", "Неизвестный код агрегата"
        )

    active = db.scalars(
        select(MaintenanceRegulation).where(
            MaintenanceRegulation.vehicle_model_id == model_id,
            MaintenanceRegulation.aggregate_type_id == aggregate_type_id,
            MaintenanceRegulation.is_archived.is_(False),
        )
    ).one_or_none()
    if active is not None:
        active.is_archived = True
        db.flush()  # архив раньше вставки: частичный UNIQUE проверяется построчно
    regulation = MaintenanceRegulation(
        vehicle_model_id=model_id,
        aggregate_type_id=aggregate_type_id,
        interval_km=interval_km,
        interval_months=interval_months,
    )
    db.add(regulation)
    db.commit()
    return db.get_one(
        MaintenanceRegulation, regulation.id, options=REGULATION_OUT, populate_existing=True
    )


def archive_regulation(db: Session, regulation_id: int) -> None:
    """DELETE /maintenance-regulations/{id} (admin): архивная или несуществующая — 404."""
    regulation = None
    if 1 <= regulation_id <= access.BIGINT_MAX:
        regulation = db.scalars(
            select(MaintenanceRegulation)
            .where(
                MaintenanceRegulation.id == regulation_id,
                MaintenanceRegulation.is_archived.is_(False),
            )
            .with_for_update()
        ).one_or_none()
    if regulation is None:
        raise ApiError(404, "REGULATION_NOT_FOUND", "Активный регламент не найден")
    regulation.is_archived = True
    db.commit()


# ---------- Пороги «светофора» ----------


def get_thresholds(db: Session) -> AggregateStatusThresholds:
    return db.get_one(AggregateStatusThresholds, THRESHOLDS_ID)


def update_thresholds(
    db: Session, user: AppUser, yellow_from_percent: int, red_above_percent: int
) -> AggregateStatusThresholds:
    """PUT /aggregate-status-thresholds (admin); порядок порогов проверила схема запроса."""
    thresholds = db.get_one(AggregateStatusThresholds, THRESHOLDS_ID, with_for_update=True)
    thresholds.yellow_from_percent = yellow_from_percent
    thresholds.red_above_percent = red_above_percent
    thresholds.updated_by_user_id = user.id
    db.commit()
    # updated_at выставляет триггер set_updated_at.
    return db.get_one(AggregateStatusThresholds, THRESHOLDS_ID, populate_existing=True)


def _thresholds(db: Session) -> Thresholds:
    row = get_thresholds(db)
    return Thresholds(row.yellow_from_percent, row.red_above_percent)


# ---------- Статусы агрегатов авто ----------


@dataclass(frozen=True)
class AggregateStatusView:
    """Ответ `AggregateStatus` контракта."""

    aggregate_type_code: str
    aggregate_type_name: str
    status: TrafficLight
    percentage: Decimal | None
    last_replaced_at: date | None
    last_replaced_mileage: int | None
    remaining_km: int | None
    remaining_days: int | None


def _view(
    aggregate_type: AggregateType,
    regulation: MaintenanceRegulation | None,
    last: VehicleAggregateStatus | None,
    vehicle: Vehicle,
    today: date,
    thresholds: Thresholds,
) -> AggregateStatusView:
    replacement = (
        None if last is None else Replacement(last.last_replaced_at, last.last_replaced_mileage)
    )
    result = None
    if regulation is not None:
        result = compute_status(
            Regulation(regulation.interval_km, regulation.interval_months),
            replacement,
            vehicle.mileage,
            today,
            thresholds,
        )
    return AggregateStatusView(
        aggregate_type_code=aggregate_type.code,
        aggregate_type_name=aggregate_type.name,
        # Без регламента выработку не рассчитать — только в ответе на замену (ADR 0016 п. 2).
        status=result.status if result else TrafficLight.UNKNOWN,
        percentage=result.percentage if result else None,
        last_replaced_at=replacement.replaced_at if replacement else None,
        last_replaced_mileage=replacement.mileage if replacement else None,
        remaining_km=result.remaining_km if result else None,
        remaining_days=result.remaining_days if result else None,
    )


def statuses_stmt(db: Session, user: AppUser, vehicle_id: int) -> tuple[Vehicle, Select]:
    """Авто (видимое `user`, иначе 404) и запрос его активных регламентов по порядку схемы."""
    vehicle = access.get_vehicle(db, user, vehicle_id)
    stmt = (
        select(MaintenanceRegulation)
        .where(
            MaintenanceRegulation.vehicle_model_id == vehicle.vehicle_model_id,
            MaintenanceRegulation.is_archived.is_(False),
        )
        .order_by(MaintenanceRegulation.aggregate_type_id)
        .options(*REGULATION_OUT)
    )
    return vehicle, stmt


def statuses_for(
    db: Session,
    vehicle: Vehicle,
    regulations: list[MaintenanceRegulation],
    today: date | None = None,
) -> list[AggregateStatusView]:
    """GET /vehicles/{id}/aggregate-statuses: статус по каждому активному регламенту."""
    today = today or today_in_business_tz()
    thresholds = _thresholds(db)
    type_ids = [r.aggregate_type_id for r in regulations]
    last = {
        s.aggregate_type_id: s
        for s in db.scalars(
            select(VehicleAggregateStatus).where(
                VehicleAggregateStatus.vehicle_id == vehicle.id,
                VehicleAggregateStatus.aggregate_type_id.in_(type_ids),
            )
        )
    }
    return [
        _view(r.aggregate_type, r, last.get(r.aggregate_type_id), vehicle, today, thresholds)
        for r in regulations
    ]


def replace_aggregate(
    db: Session,
    user: AppUser,
    vehicle_id: int,
    aggregate_type_code: str,
    *,
    replaced_at: date,
    mileage_at_replacement: int,
    description: str | None,
    today: date | None = None,
) -> AggregateStatusView:
    """POST /vehicles/{id}/aggregate-statuses/{code}/replace (engineer/admin), ADR 0016 п. 2.

    Всегда пишет историю ТО; текущую замену меняет по правилу E5/E6 (`becomes_current`).
    Строка авто заблокирована `access.for_change` — замены одного авто идут по очереди.
    """
    today = today or today_in_business_tz()
    vehicle, ticket_id = access.for_change(db, user, vehicle_id)
    aggregate_type = db.scalars(
        select(AggregateType).where(AggregateType.code == aggregate_type_code)
    ).one_or_none()
    if aggregate_type is None:
        raise ApiError(404, "AGGREGATE_TYPE_NOT_FOUND", "Неизвестный код агрегата")
    if replaced_at > today:
        raise _field_error("replaced_at", "REPLACED_AT_IN_FUTURE", "Дата замены в будущем")
    if mileage_at_replacement > vehicle.mileage:
        raise ApiError(
            409,
            "MILEAGE_AHEAD_OF_VEHICLE",
            "Пробег замены больше пробега авто — сначала обновите пробег",
            details={"current_mileage": vehicle.mileage},
        )

    db.add(
        MaintenanceRecord(
            vehicle_id=vehicle.id,
            aggregate_type_id=aggregate_type.id,
            performed_by_user_id=user.id,
            ticket_id=ticket_id,
            performed_at=replaced_at,
            mileage_at_service=mileage_at_replacement,
            description=description,
        )
    )
    last = db.scalars(
        select(VehicleAggregateStatus)
        .where(
            VehicleAggregateStatus.vehicle_id == vehicle.id,
            VehicleAggregateStatus.aggregate_type_id == aggregate_type.id,
        )
        .with_for_update()
    ).one_or_none()
    if last is None:
        last = VehicleAggregateStatus(vehicle_id=vehicle.id, aggregate_type_id=aggregate_type.id)
        db.add(last)
    current = Replacement(last.last_replaced_at, last.last_replaced_mileage)
    if becomes_current(current, replaced_at):
        last.last_replaced_at = replaced_at
        last.last_replaced_mileage = mileage_at_replacement
    db.commit()

    regulation = db.scalars(
        select(MaintenanceRegulation).where(
            MaintenanceRegulation.vehicle_model_id == vehicle.vehicle_model_id,
            MaintenanceRegulation.aggregate_type_id == aggregate_type.id,
            MaintenanceRegulation.is_archived.is_(False),
        )
    ).one_or_none()
    return _view(aggregate_type, regulation, last, vehicle, today, _thresholds(db))
