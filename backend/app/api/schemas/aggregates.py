"""Схемы Aggregates & Maintenance — по components/schemas docs/openapi.yaml (ADR 0007, 0016)."""

import unicodedata
from datetime import date, datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.api.pagination import PaginationMeta
from app.api.schemas.common import no_control_chars
from app.core.db import BIGINT_MAX
from app.domain.aggregates import TrafficLight

INT_MAX = 2_147_483_647  # INTEGER в БД
# Больше — add_months выходит за год 9999 (ValueError → 500); 100 лет хватает любому регламенту.
INTERVAL_MONTHS_MAX = 1200


class AggregateTypeCreateRequest(BaseModel):
    code: Annotated[str, Field(max_length=50, pattern=r"^[a-z][a-z0-9_]{1,49}$")]
    name: Annotated[str, Field(min_length=1, max_length=100)]

    @field_validator("name")
    @classmethod
    def _name(cls, value: str) -> str:
        # NFC: «й» одним символом, как в справочнике (миграция 0007), а не «и» + U+0306.
        value = unicodedata.normalize("NFC", no_control_chars(value.strip()))
        if not value:
            raise ValueError("название не может быть пустым")
        return value


class MaintenanceRegulationCreateRequest(BaseModel):
    vehicle_model_id: Annotated[int, Field(le=BIGINT_MAX)]
    aggregate_type_code: Annotated[str, Field(max_length=50)]
    interval_km: Annotated[int | None, Field(ge=1, le=INT_MAX)] = None
    interval_months: Annotated[int | None, Field(ge=1, le=INTERVAL_MONTHS_MAX)] = None

    @model_validator(mode="after")
    def _interval_present(self) -> "MaintenanceRegulationCreateRequest":
        if self.interval_km is None and self.interval_months is None:
            raise ValueError("нужно указать interval_km и/или interval_months")
        return self


class AggregateReplaceRequest(BaseModel):
    replaced_at: date
    mileage_at_replacement: Annotated[int, Field(ge=0, le=INT_MAX)]
    description: Annotated[str | None, Field(max_length=255)] = None  # maintenance_record

    @field_validator("description")
    @classmethod
    def _description(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return no_control_chars(value.strip()) or None


class AggregateStatusThresholdsUpdateRequest(BaseModel):
    yellow_from_percent: Annotated[int, Field(ge=1, le=199)]
    red_above_percent: Annotated[int, Field(ge=2, le=200)]

    @model_validator(mode="after")
    def _order(self) -> "AggregateStatusThresholdsUpdateRequest":
        if self.yellow_from_percent >= self.red_above_percent:
            raise ValueError("нужно yellow_from_percent < red_above_percent")
        return self


# Ответы строятся из ORM-объектов (from_attributes); связи загружает сервис (ADR 0015).


class AggregateTypeOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    code: str
    name: str


class MaintenanceRegulationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    vehicle_model_id: int
    aggregate_type_code: str
    interval_km: int | None
    interval_months: int | None
    is_archived: bool


class AggregateStatusOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    aggregate_type_code: str
    aggregate_type_name: str
    status: TrafficLight
    percentage: float | None  # Decimal сериализуется строкой, в контракте — number
    last_replaced_at: date | None
    last_replaced_mileage: int | None
    remaining_km: int | None
    remaining_days: int | None


class AggregateStatusThresholdsOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    yellow_from_percent: int
    red_above_percent: int
    updated_at: datetime
    updated_by_user_id: int | None


class AggregateTypeList(BaseModel):
    items: list[AggregateTypeOut]
    meta: PaginationMeta


class MaintenanceRegulationList(BaseModel):
    items: list[MaintenanceRegulationOut]
    meta: PaginationMeta


class AggregateStatusList(BaseModel):
    items: list[AggregateStatusOut]
    meta: PaginationMeta
