"""Схемы Vehicle Service — по components/schemas docs/openapi.yaml (ADR 0007, ADR 0014)."""

from datetime import date, datetime
from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.api.pagination import PaginationMeta
from app.api.schemas.auth import UserPublic
from app.api.schemas.common import no_control_chars
from app.domain.vehicles.vin import VIN_PATTERN, validate_vin


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
        value = no_control_chars(value.strip())
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
        return no_control_chars(value.strip()) or None


# Ответы строятся из ORM-объектов (from_attributes); связи загружает сервис (ADR 0015).


class VehicleModelInfo(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    brand: str
    model: str
    trim: str | None = None

    @field_validator("trim", mode="before")
    @classmethod
    def _trim(cls, value: str | None) -> str | None:
        return value or None  # '' в БД = без комплектации (UNIQUE не работает с NULL)


class VehicleModelOut(VehicleModelInfo):
    id: int


class VehicleOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    vin: str
    mileage: int
    is_active: bool
    vehicle_model_id: int
    vehicle_model: VehicleModelInfo
    current_firmware_version: str | None = None
    created_at: datetime


class MaintenanceRecordOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    aggregate_type_code: str | None
    # Не nullable в контракте: без автора (импорт истории) поле не выводится.
    performed_by: UserPublic | None = Field(None, exclude_if=lambda v: v is None)
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
