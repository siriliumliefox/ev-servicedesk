"""Схемы Uploads — по components/schemas docs/openapi.yaml 1.4.0 (ADR 0004, ADR 0017 п. 10)."""

from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import AttachmentType


class PresignRequest(BaseModel):
    # Из имени берётся только расширение; само имя не хранится и не пишется в логи (ПД).
    file_name: Annotated[str, Field(min_length=1, max_length=255)]
    file_type: AttachmentType


class PresignResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    upload_url: str
    file_url: str  # ключ объекта uploads/{user_id}/{uuid}{расширение}, не публичная ссылка
    expires_at: datetime
