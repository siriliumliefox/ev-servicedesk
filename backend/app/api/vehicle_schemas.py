"""Схемы Vehicle Service — по components/schemas docs/openapi.yaml (ADR 0007, ADR 0014)."""

from datetime import date, datetime
from typing import Annotated, Any

from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.pagination import PaginationMeta
from app.api.schemas import UserPublic, _no_control_chars
from app.domain.vehicles.vin import VIN_PATTERN, validate_vin
from app.models import AggregateType, AppUser, MaintenanceRecord, Vehicle, VehicleModel
from app.models.vehicles import FirmwareRelease


class VehicleCreateRequest(BaseModel):
    vin: Annotated[
        str,
        Field(
            min_length=17,
            max_length=17,
            pattern=VIN_PATTERN.pattern,
            examples=["L6TZ0010000000001"],
        ),
    ]
    vehicle_model_id: int | None = None

    @field_validator("vin", mode="before")
    @classmethod
    def _vin(cls, value: Any) -> Any:
        # Причина (длина, I/O/Q, символ) — в details ответа 422 вместо общего «не по шаблону».
        return validate_vin(value) if isinstance(value, str) else value


class MileageUpdateRequest(BaseModel):
    mileage: Annotated[int, Field(ge=0, le=2_147_483_647)]  # INTEGER в БД


class MileageCorrectionRequest(BaseModel):
    expected_current_mileage: Annotated[int, Field(ge=0, le=2_147_483_647)]
    mileage: Annotated[int, Field(ge=0, le=2_147_483_647)]
    reason: Annotated[str, Field(min_length=1, max_length=500)]

    @field_validator("reason")
    @classmethod
    def _reason(cls, value: str) -> str:
        value = _no_control_chars(value.strip())
        if not value:
            raise ValueError("причина не может быть пустой")
        return value


class MaintenanceRecordCreateRequest(BaseModel):
    aggregate_type_code: Annotated[str | None, Field(max_length=50)] = None
    performed_at: date
    mileage_at_service: Annotated[int, Field(ge=0, le=2_147_483_647)]
    description: Annotated[str | None, Field(max_length=255)] = None

    @field_validator("description")
    @classmethod
    def _description(cls, value: str | None) -> str | None:
        """Пробелы по краям отбрасываются; пустая строка = описание не передано."""
        if value is None:
            return None
        return _no_control_chars(value.strip()) or None


class VehicleModelInfo(BaseModel):
    brand: str
    model: str
    trim: str | None = None


class VehicleModelOut(VehicleModelInfo):
    id: int


class VehicleOut(BaseModel):
    id: int
    vin: str
    mileage: int
    is_active: bool
    vehicle_model: VehicleModelInfo
    current_firmware_version: str | None = None
    created_at: datetime


class MaintenanceRecordOut(BaseModel):
    id: int
    aggregate_type_code: str | None
    # Не nullable в контракте: при отсутствии автора поле не выводится (exclude_unset).
    performed_by: UserPublic | None = None
    performed_at: date
    mileage_at_service: int
    description: str | None


class VehicleModelList(BaseModel):
    items: list[VehicleModelOut]
    meta: PaginationMeta


class VehicleList(BaseModel):
    items: list[VehicleOut]
    meta: PaginationMeta


class MaintenanceRecordList(BaseModel):
    items: list[MaintenanceRecordOut]
    meta: PaginationMeta


# ---------- ORM → ответ (пакетно, без запроса на каждую строку) ----------


def model_out(model: VehicleModel) -> VehicleModelOut:
    return VehicleModelOut(
        id=model.id, brand=model.brand, model=model.model, trim=model.trim or None
    )


def vehicles_out(db: Session, vehicles: list[Vehicle]) -> list[VehicleOut]:
    model_ids = {v.vehicle_model_id for v in vehicles}
    firmware_ids = {v.current_firmware_release_id for v in vehicles} - {None}
    models = {
        m.id: m for m in db.scalars(select(VehicleModel).where(VehicleModel.id.in_(model_ids)))
    }
    firmware = dict(
        db.execute(
            select(FirmwareRelease.id, FirmwareRelease.version).where(
                FirmwareRelease.id.in_(firmware_ids)
            )
        ).all()
    )
    out = []
    for v in vehicles:
        m = models[v.vehicle_model_id]
        out.append(
            VehicleOut(
                id=v.id,
                vin=v.vin,
                mileage=v.mileage,
                is_active=v.deleted_at is None,
                vehicle_model=VehicleModelInfo(brand=m.brand, model=m.model, trim=m.trim or None),
                current_firmware_version=firmware.get(v.current_firmware_release_id),
                created_at=v.created_at,
            )
        )
    return out


def vehicle_out(db: Session, vehicle: Vehicle) -> VehicleOut:
    return vehicles_out(db, [vehicle])[0]


def records_out(db: Session, records: list[MaintenanceRecord]) -> list[MaintenanceRecordOut]:
    type_ids = {r.aggregate_type_id for r in records} - {None}
    user_ids = {r.performed_by_user_id for r in records} - {None}
    codes = dict(
        db.execute(
            select(AggregateType.id, AggregateType.code).where(AggregateType.id.in_(type_ids))
        ).all()
    )
    users = {u.id: u for u in db.scalars(select(AppUser).where(AppUser.id.in_(user_ids)))}
    out = []
    for r in records:
        fields: dict[str, Any] = {
            "id": r.id,
            "aggregate_type_code": codes.get(r.aggregate_type_id),
            "performed_at": r.performed_at,
            "mileage_at_service": r.mileage_at_service,
            "description": r.description,
        }
        if r.performed_by_user_id is not None:
            fields["performed_by"] = UserPublic.model_validate(users[r.performed_by_user_id])
        out.append(MaintenanceRecordOut(**fields))
    return out
