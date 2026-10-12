"""Схемы Notifications — по components/schemas docs/openapi.yaml 1.6.0 (ADR 0007, ADR 0019).

Пределы текста проверяют валидаторы, а не maxLength контракта: новый maxLength в запросе
`oasdiff` считает ломающим (как длины тикетов и статей, ADR 0017 п. 13, ADR 0018 п. 10).
"""

import unicodedata
from datetime import date, datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.api.pagination import PaginationMeta
from app.api.schemas.common import no_control_chars, no_control_chars_multiline
from app.core.db import BIGINT_MAX
from app.models.enums import NotificationType
from app.models.notifications import PUSH_TOKEN_MAX_LENGTH

MESSAGE_MAX = 1000
VERSION_MAX = 50

DbId = Annotated[int, Field(ge=1, le=BIGINT_MAX)]


class PushTokenRegisterRequest(BaseModel):
    token: Annotated[str, Field(min_length=1, max_length=4096)]

    @field_validator("token")
    @classmethod
    def _token(cls, value: str) -> str:
        """Длина колонки — 1024 (ADR 0019 п. 8); токены FCM заметно короче."""
        no_control_chars(value)
        if len(value) > PUSH_TOKEN_MAX_LENGTH:
            raise ValueError(f"не больше {PUSH_TOKEN_MAX_LENGTH} символов")
        return value


class NotificationOpenedRequest(PushTokenRegisterRequest):
    """Токен устройства, на котором открыт push; проверки — как при регистрации."""


class NotificationCreateRequest(BaseModel):
    type: NotificationType
    target_vehicle_model_id: DbId | None = None
    firmware_release_id: DbId | None = None
    message: str

    @field_validator("message")
    @classmethod
    def _message(cls, value: str) -> str:
        """1–1000 символов после обрезки пробелов, NFC, без управляющих (ADR 0019 п. 11)."""
        value = unicodedata.normalize("NFC", no_control_chars_multiline(value.strip()))
        if not value:
            raise ValueError("текст не может быть пустым")
        if len(value) > MESSAGE_MAX:
            raise ValueError(f"не больше {MESSAGE_MAX} символов")
        return value


class FirmwareReleaseCreateRequest(BaseModel):
    vehicle_model_id: int
    version: Annotated[str, Field(min_length=1, max_length=VERSION_MAX)]
    released_at: date

    @field_validator("version")
    @classmethod
    def _version(cls, value: str) -> str:
        value = unicodedata.normalize("NFC", no_control_chars(value.strip()))
        if not value:
            raise ValueError("версия не может быть пустой")
        return value


class VehicleFirmwareUpdateRequest(BaseModel):
    firmware_release_id: int


class NotificationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    type: NotificationType
    target_vehicle_model_id: int | None
    firmware_release_id: int | None
    vehicle_id: int | None
    aggregate_type_id: int | None
    message: str
    created_at: datetime


class NotificationListItem(NotificationOut):
    read_at: datetime | None


class NotificationList(BaseModel):
    items: list[NotificationListItem]
    meta: PaginationMeta


class NotificationDeliveryStats(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    recipients: int
    delivered: int
    failed: int
    opened: int
    read: int


class PublishedNotification(NotificationOut):
    stats: NotificationDeliveryStats


class PublishedNotificationList(BaseModel):
    items: list[PublishedNotification]
    meta: PaginationMeta


class NotificationAudiencePreview(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    recipients: int
    devices: int


class FirmwareReleaseOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    vehicle_model_id: int
    version: str
    released_at: date


class FirmwareReleaseList(BaseModel):
    items: list[FirmwareReleaseOut]
    meta: PaginationMeta
