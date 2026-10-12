"""Схемы Tickets Service — по components/schemas docs/openapi.yaml 1.4.0 (ADR 0007, ADR 0017).

Ответы с вложениями и автором сообщения зависят от получателя: file_url — presigned GET,
ПД сотрудника скрыты от клиента. Поэтому их собирают функции `ticket_detail_out` и
`message_out` (общие для REST и WebSocket), а не валидаторы с контекстом: FastAPI повторно
валидирует возвращённую модель, и валидаторы ответа должны быть идемпотентны.
"""

from collections.abc import Callable
from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.api.pagination import PaginationMeta
from app.api.schemas.aggregates import AggregateStatusOut
from app.api.schemas.auth import UserPublic
from app.api.schemas.common import no_control_chars_multiline
from app.api.schemas.vehicles import VehicleModelInfo, VehicleOut
from app.core.db import BIGINT_MAX
from app.domain.tickets import access
from app.domain.tickets.card import TicketCard
from app.models import AppUser, KnowledgeArticleRevision, TicketAttachment, TicketMessage
from app.models.enums import AttachmentType, TicketCategory, TicketStatus

TEXT_MAX_LENGTH = 4000  # description и body: после обрезки пробелов (ADR 0017 п. 7–8, 13)


def _text(value: str) -> str:
    value = value.strip()
    if not value:
        raise ValueError("текст не может быть пустым")
    if len(value) > TEXT_MAX_LENGTH:
        raise ValueError(f"не больше {TEXT_MAX_LENGTH} символов")
    return no_control_chars_multiline(value)


class TicketAttachmentInput(BaseModel):
    file_url: Annotated[str, Field(min_length=1, max_length=500)]
    file_type: AttachmentType


class TicketCreateRequest(BaseModel):
    vehicle_id: int
    category: TicketCategory
    # Длина — после обрезки пробелов, поэтому проверяет валидатор, а не maxLength схемы.
    description: str
    source_article_id: int | None = None
    source_node_id: int | None = None
    attachments: list[TicketAttachmentInput] = []

    _check_description = field_validator("description")(_text)


class TicketStatusUpdateRequest(BaseModel):
    status: TicketStatus


class TicketAssignRequest(BaseModel):
    # Без значения по умолчанию: поле обязательно, null — снять инженера.
    assigned_engineer_id: Annotated[int | None, Field(le=BIGINT_MAX)]


class TicketMessageCreateRequest(BaseModel):
    body: str
    attachments: list[TicketAttachmentInput] = []

    _check_body = field_validator("body")(_text)


# ---------- Ответы ----------


class TicketAttachmentOut(BaseModel):
    file_url: str  # presigned GET на 15 минут (ADR 0017 п. 10)
    file_type: AttachmentType


class TicketOut(BaseModel):
    """Элемент списка и событие ticket.updated; связи загружает сервис (ADR 0015)."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    vehicle_id: int
    vehicle_model: VehicleModelInfo
    summary: str
    category: TicketCategory
    status: TicketStatus
    assigned_engineer_id: int | None
    sla_due_at: datetime
    is_overdue: bool
    created_at: datetime
    resolved_at: datetime | None


class TicketSourceArticleOut(BaseModel):
    """«Пометка» эскалации: статья в той версии, которую видел клиент (ADR 0018 п. 11)."""

    id: int
    title: str
    version: int


class VehicleContextOut(BaseModel):
    vehicle: VehicleOut
    aggregate_statuses: list[AggregateStatusOut]


class TicketDetailOut(TicketOut):
    description: str
    firmware_version_at_creation: str | None
    source_article: TicketSourceArticleOut | None
    attachments: list[TicketAttachmentOut]
    vehicle_context: VehicleContextOut


class TicketMessageOut(BaseModel):
    id: int
    author: UserPublic
    body: str
    attachments: list[TicketAttachmentOut]
    created_at: datetime


class TicketList(BaseModel):
    items: list[TicketOut]
    meta: PaginationMeta


class TicketMessageList(BaseModel):
    items: list[TicketMessageOut]
    meta: PaginationMeta


# ---------- Сборка ответов для получателя ----------

# file_url вложения при чтении: presigned GET (зависимость `PresignDep`, ADR 0017 п. 10).
Presign = Callable[[TicketAttachment], str]


def _attachments(items: list[TicketAttachment], presign: Presign) -> list[TicketAttachmentOut]:
    return [TicketAttachmentOut(file_url=presign(a), file_type=a.file_type) for a in items]


def _source_article(revision: KnowledgeArticleRevision | None) -> TicketSourceArticleOut | None:
    if revision is None:
        return None
    return TicketSourceArticleOut(
        id=revision.article_id, title=revision.title, version=revision.version
    )


def ticket_detail_out(card: TicketCard, presign: Presign) -> TicketDetailOut:
    ticket = card.ticket
    return TicketDetailOut(
        **dict(TicketOut.model_validate(ticket)),
        description=ticket.description,
        firmware_version_at_creation=ticket.firmware_version_at_creation,
        source_article=_source_article(ticket.source_article),
        attachments=_attachments(ticket.attachments, presign),
        vehicle_context=VehicleContextOut(
            vehicle=VehicleOut.model_validate(ticket.vehicle),
            aggregate_statuses=[
                AggregateStatusOut.model_validate(v) for v in card.aggregate_statuses
            ],
        ),
    )


def message_out(message: TicketMessage, viewer: AppUser, presign: Presign) -> TicketMessageOut:
    """Сообщение глазами `viewer`: клиенту телефон и Telegram сотрудника — null (п. 12)."""
    author = UserPublic.model_validate(message.author)
    if access.hides_staff_contacts(viewer, message.author):
        author = author.model_copy(update={"phone": None, "telegram_id": None})
    return TicketMessageOut(
        id=message.id,
        author=author,
        body=message.body,
        attachments=_attachments(message.attachments, presign),
        created_at=message.created_at,
    )
