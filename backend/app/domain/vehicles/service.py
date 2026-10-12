"""Сценарии Vehicle Service (Глава 11, ADR 0014). Доступ к конкретному авто — `access`.

Ограничения БД (vehicle_guard, триггеры журнала пробега, uq_vehicle_vin_active) остаются
последней линией защиты; здесь те же правила проверяются заранее, а нарушение ограничения
в гонке переводится в объявленный контрактом ответ, а не в 500.

Сценарии возвращают объекты со связями, загруженными для ответа (`VEHICLE_OUT`,
`RECORD_OUT`): ленивая подгрузка в моделях запрещена (ADR 0015).
"""

from datetime import UTC, date, datetime

from redis import Redis
from sqlalchemy import Select, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from app.core import rate_limit
from app.core.config import Settings
from app.core.db import constraint_name, escape_like
from app.core.errors import ApiError
from app.core.time import BUSINESS_TZ
from app.domain.vehicles import access
from app.domain.vehicles.vin import VinDecoder
from app.models import AggregateType, AppUser, MaintenanceRecord, Vehicle, VehicleModel
from app.models.vehicles import VehicleMileageCorrection

VEHICLE_OUT = (selectinload(Vehicle.vehicle_model),)
RECORD_OUT = (
    selectinload(MaintenanceRecord.aggregate_type),
    selectinload(MaintenanceRecord.performed_by),
)


def _reload_vehicle(db: Session, vehicle_id: int) -> Vehicle:
    """Состояние после commit (пробег и updated_at меняют триггеры) вместе с моделью."""
    return db.get_one(Vehicle, vehicle_id, options=VEHICLE_OUT, populate_existing=True)


# ---------- Модели ----------


def search_models_stmt(search: str | None) -> Select:
    stmt = select(VehicleModel).order_by(VehicleModel.brand, VehicleModel.model, VehicleModel.trim)
    if search and search.strip():
        pattern = f"%{escape_like(search.strip())}%"
        # Подстрока марки или модели — тоже подстрока «марка модель».
        brand_model = VehicleModel.brand + " " + VehicleModel.model
        stmt = stmt.where(brand_model.ilike(pattern, escape="\\"))
    return stmt


# ---------- Авто клиента ----------


def list_vehicles_stmt(user: AppUser) -> Select:
    return (
        select(Vehicle)
        .where(Vehicle.user_id == user.id, Vehicle.deleted_at.is_(None))
        .order_by(Vehicle.created_at, Vehicle.id)
        .options(*VEHICLE_OUT)
    )


def _vin_conflict(db: Session, user: AppUser, vin: str) -> ApiError | None:
    owner_id = db.scalar(
        select(Vehicle.user_id).where(Vehicle.vin == vin, Vehicle.deleted_at.is_(None))
    )
    if owner_id is None:
        return None
    if owner_id == user.id:
        return ApiError(409, "VIN_ALREADY_ADDED", "Этот автомобиль уже добавлен в ваш аккаунт")
    # Владелец, его телефон и id авто не раскрываются (ПД, ADR 0014).
    return ApiError(
        409,
        "VIN_REGISTERED_TO_ANOTHER_ACCOUNT",
        "Автомобиль привязан к другому аккаунту — обратитесь в поддержку",
    )


def _resolve_model(
    db: Session, decoder: VinDecoder, vin: str, vehicle_model_id: int | None
) -> VehicleModel:
    if vehicle_model_id is not None:
        model = db.get(VehicleModel, vehicle_model_id)
        if model is None:
            raise ApiError(
                422,
                "VEHICLE_MODEL_NOT_FOUND",
                "Модель не найдена",
                details={"fields": [{"loc": ["body", "vehicle_model_id"]}]},
            )
        return model
    decoded = decoder.decode(vin)
    model = None
    if decoded is not None:
        model = db.scalars(
            select(VehicleModel).where(
                VehicleModel.brand == decoded.brand,
                VehicleModel.model == decoded.model,
                VehicleModel.trim == decoded.trim,
            )
        ).one_or_none()
    if model is None:
        raise ApiError(
            422,
            "VIN_DECODE_FAILED",
            "Не удалось определить модель по VIN — выберите модель вручную",
        )
    return model


def create_vehicle(
    db: Session,
    redis: Redis,
    settings: Settings,
    decoder: VinDecoder,
    user: AppUser,
    vin: str,
    vehicle_model_id: int | None,
) -> Vehicle:
    """POST /vehicles. Своё удалённое авто с тем же VIN восстанавливается с историей."""
    rate_limit.enforce(
        redis,
        f"vehicle-create:{user.id}",
        3600,
        settings.vehicle_create_per_user_hour,
        "Слишком много попыток добавить автомобиль",
    )

    if (conflict := _vin_conflict(db, user, vin)) is not None:
        raise conflict

    restored = db.scalars(
        select(Vehicle)
        .where(Vehicle.vin == vin, Vehicle.user_id == user.id, Vehicle.deleted_at.is_not(None))
        .order_by(Vehicle.deleted_at.desc(), Vehicle.id.desc())
        .limit(1)
        .with_for_update()
    ).one_or_none()
    if restored is not None:
        # Модель неизменяема (vehicle_guard): vehicle_model_id запроса здесь не применяется.
        restored.deleted_at = None
        vehicle = restored
    else:
        model = _resolve_model(db, decoder, vin, vehicle_model_id)
        vehicle = Vehicle(user_id=user.id, vehicle_model_id=model.id, vin=vin)
        db.add(vehicle)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        if constraint_name(exc) != "uq_vehicle_vin_active":
            raise
        # Параллельное добавление того же VIN: проигравший получает тот же 409.
        conflict = _vin_conflict(db, user, vin)
        if conflict is None:
            raise
        raise conflict from exc
    db.commit()
    return _reload_vehicle(db, vehicle.id)


def get_vehicle(db: Session, user: AppUser, vehicle_id: int) -> Vehicle:
    """GET /vehicles/{id}."""
    return access.get_vehicle(db, user, vehicle_id, *VEHICLE_OUT)


def delete_vehicle(db: Session, user: AppUser, vehicle_id: int) -> None:
    """DELETE /vehicles/{id}: soft-delete; тикеты и история работ остаются (ADR 0003)."""
    vehicle = access.for_change(db, user, vehicle_id).vehicle
    vehicle.deleted_at = datetime.now(UTC)
    db.commit()


# ---------- Пробег ----------


def update_mileage(db: Session, user: AppUser, vehicle_id: int, mileage: int) -> Vehicle:
    """PATCH /vehicles/{id}/mileage: только вверх; равное значение — без изменений."""
    vehicle = access.for_change(db, user, vehicle_id).vehicle
    if mileage < vehicle.mileage:
        raise ApiError(
            409,
            "MILEAGE_DECREASE",
            "Пробег не может уменьшаться",
            details={"current_mileage": vehicle.mileage},
        )
    vehicle.mileage = mileage
    db.commit()
    return _reload_vehicle(db, vehicle.id)


def correct_mileage(
    db: Session,
    user: AppUser,
    vehicle_id: int,
    expected_current_mileage: int,
    mileage: int,
    reason: str,
) -> Vehicle:
    """POST /vehicles/{id}/mileage-corrections: уменьшение пробега через журнал (ADR 0006)."""
    vehicle = access.for_change(db, user, vehicle_id).vehicle
    if expected_current_mileage != vehicle.mileage:
        raise ApiError(
            409,
            "MILEAGE_CORRECTION_STALE",
            "Пробег изменился — обновите карточку",
            details={"current_mileage": vehicle.mileage},
        )
    if mileage >= vehicle.mileage:
        raise ApiError(
            409,
            "MILEAGE_NOT_DECREASED",
            "Исправление только уменьшает пробег; для увеличения — обновление пробега",
            details={"current_mileage": vehicle.mileage},
        )
    db.add(
        VehicleMileageCorrection(
            vehicle_id=vehicle.id,
            corrected_by_user_id=user.id,
            old_mileage=vehicle.mileage,
            new_mileage=mileage,
            reason=reason,
        )
    )
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        if constraint_name(exc) == "mileage_correction_stale":
            raise ApiError(409, "MILEAGE_CORRECTION_STALE", "Пробег изменился") from exc
        raise
    db.commit()
    return _reload_vehicle(db, vehicle.id)  # пробег поменял триггер AFTER INSERT


# ---------- История работ ----------


def list_maintenance_stmt(db: Session, user: AppUser, vehicle_id: int) -> Select:
    access.get_vehicle(db, user, vehicle_id)
    return (
        select(MaintenanceRecord)
        .where(MaintenanceRecord.vehicle_id == vehicle_id)
        .order_by(MaintenanceRecord.performed_at.desc(), MaintenanceRecord.id.desc())
        .options(*RECORD_OUT)
    )


def _field_error(field: str, code: str, message: str) -> ApiError:
    return ApiError(422, code, message, details={"fields": [{"loc": ["body", field]}]})


def create_maintenance_record(
    db: Session,
    user: AppUser,
    vehicle_id: int,
    *,
    aggregate_type_code: str | None,
    performed_at: date,
    mileage_at_service: int,
    description: str | None,
) -> MaintenanceRecord:
    """POST /vehicles/{id}/maintenance-records (engineer/admin).

    Пробег на момент работы выше текущего поднимает пробег авто; записи задним числом
    (ниже текущего) допустимы. Тикет-основание даёт `access` (у админа — нет).
    Сброс счётчика агрегата — Глава 12.
    """
    vehicle, ticket_id = access.for_change(db, user, vehicle_id)
    if performed_at > datetime.now(BUSINESS_TZ).date():
        raise _field_error("performed_at", "PERFORMED_AT_IN_FUTURE", "Дата работы в будущем")

    aggregate_type_id = None
    if aggregate_type_code is not None:
        aggregate_type_id = db.scalar(
            select(AggregateType.id).where(AggregateType.code == aggregate_type_code)
        )
        if aggregate_type_id is None:
            raise _field_error(
                "aggregate_type_code", "AGGREGATE_TYPE_NOT_FOUND", "Неизвестный код агрегата"
            )
    if aggregate_type_id is None and description is None:
        raise _field_error(
            "description", "MAINTENANCE_SUBJECT_REQUIRED", "Укажите агрегат или описание работы"
        )

    if mileage_at_service > vehicle.mileage:
        vehicle.mileage = mileage_at_service
    record = MaintenanceRecord(
        vehicle_id=vehicle.id,
        aggregate_type_id=aggregate_type_id,
        performed_by_user_id=user.id,
        ticket_id=ticket_id,
        performed_at=performed_at,
        mileage_at_service=mileage_at_service,
        description=description,
    )
    db.add(record)
    db.commit()
    return db.get_one(MaintenanceRecord, record.id, options=RECORD_OUT, populate_existing=True)
