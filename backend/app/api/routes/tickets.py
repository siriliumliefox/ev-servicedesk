"""Tickets Service — пути `/tickets*` контракта (тег Tickets, Глава 13, ADR 0017).

Реал-тайм доставка событий — WebSocket `/tickets/{ticketId}/ws` (`ticket_events`).
"""

from typing import Annotated

from fastapi import APIRouter, Path, Query, status
from pydantic import AwareDatetime

from app.api.deps import (
    ALL_ROLES,
    CurrentUser,
    DbDep,
    PresignDep,
    RedisDep,
    SettingsDep,
    StorageDep,
    TicketEventsDep,
    rbac,
)
from app.api.pagination import PageDep, paginate
from app.api.schemas.tickets import (
    TicketAssignRequest,
    TicketCreateRequest,
    TicketDetailOut,
    TicketList,
    TicketMessageCreateRequest,
    TicketMessageList,
    TicketMessageOut,
    TicketOut,
    TicketStatusUpdateRequest,
    message_out,
    ticket_detail_out,
)
from app.core.db import BIGINT_MAX
from app.domain.tickets import service
from app.models.enums import STAFF_ROLES, TicketCategory, TicketStatus, UserRole

router = APIRouter(tags=["Tickets"])


# Диапазон BIGINT проверяет access (вне диапазона — 404, как у несуществующего id).
TicketId = Annotated[int, Path(alias="ticketId")]


@router.get("/tickets", operation_id="listTickets", **rbac(*ALL_ROLES))
def list_tickets(
    user: CurrentUser,
    db: DbDep,
    page: PageDep,
    ticket_status: Annotated[TicketStatus | None, Query(alias="status")] = None,
    category: TicketCategory | None = None,
    # Диапазон BIGINT: вне его — ошибка драйвера и 500, а не 422.
    assigned_engineer_id: Annotated[int | None, Query(ge=-BIGINT_MAX - 1, le=BIGINT_MAX)] = None,
    overdue: bool | None = None,
    # Только со смещением (RFC 3339): время без зоны неоднозначно — 422 (ADR 0025 п. 9).
    resolved_since: AwareDatetime | None = None,
) -> TicketList:
    stmt = service.list_tickets_stmt(
        user,
        status=ticket_status,
        category=category,
        assigned_engineer_id=assigned_engineer_id,
        overdue=overdue,
        resolved_since=resolved_since,
    )
    items, meta = paginate(db, stmt, page)
    return TicketList(items=[TicketOut.model_validate(t) for t in items], meta=meta)


@router.post(
    "/tickets",
    operation_id="createTicket",
    status_code=status.HTTP_201_CREATED,
    **rbac(UserRole.CLIENT),
)
def create_ticket(
    body: TicketCreateRequest,
    user: CurrentUser,
    db: DbDep,
    redis: RedisDep,
    settings: SettingsDep,
    storage: StorageDep,
    presign: PresignDep,
) -> TicketDetailOut:
    card = service.create_ticket(
        db,
        redis,
        settings,
        storage,
        user,
        vehicle_id=body.vehicle_id,
        category=body.category,
        description=body.description,
        source_article_id=body.source_article_id,
        source_node_id=body.source_node_id,
        attachment_inputs=body.attachments,
    )
    return ticket_detail_out(card, presign)


@router.get("/tickets/{ticketId}", operation_id="getTicket", **rbac(*ALL_ROLES))
def get_ticket(
    ticket_id: TicketId,
    user: CurrentUser,
    db: DbDep,
    presign: PresignDep,
) -> TicketDetailOut:
    card = service.get_ticket(db, user, ticket_id)
    return ticket_detail_out(card, presign)


@router.patch("/tickets/{ticketId}/status", operation_id="updateTicketStatus", **rbac(*STAFF_ROLES))
def update_ticket_status(
    ticket_id: TicketId,
    body: TicketStatusUpdateRequest,
    user: CurrentUser,
    db: DbDep,
    events: TicketEventsDep,
    presign: PresignDep,
) -> TicketDetailOut:
    card = service.change_status(db, events, user, ticket_id, body.status)
    return ticket_detail_out(card, presign)


@router.post("/tickets/{ticketId}/claim", operation_id="claimTicket", **rbac(UserRole.ENGINEER))
def claim_ticket(
    ticket_id: TicketId,
    user: CurrentUser,
    db: DbDep,
    events: TicketEventsDep,
    presign: PresignDep,
) -> TicketDetailOut:
    card = service.claim_ticket(db, events, user, ticket_id)
    return ticket_detail_out(card, presign)


@router.patch("/tickets/{ticketId}/assign", operation_id="assignTicket", **rbac(UserRole.ADMIN))
def assign_ticket(
    ticket_id: TicketId,
    body: TicketAssignRequest,
    user: CurrentUser,
    db: DbDep,
    events: TicketEventsDep,
    presign: PresignDep,
) -> TicketDetailOut:
    card = service.assign_ticket(db, events, user, ticket_id, body.assigned_engineer_id)
    return ticket_detail_out(card, presign)


@router.get("/tickets/{ticketId}/messages", operation_id="listTicketMessages", **rbac(*ALL_ROLES))
def list_ticket_messages(
    ticket_id: TicketId,
    user: CurrentUser,
    db: DbDep,
    page: PageDep,
    presign: PresignDep,
    after_id: Annotated[int | None, Query(ge=0, le=BIGINT_MAX)] = None,
) -> TicketMessageList:
    items, meta = paginate(db, service.list_messages_stmt(db, user, ticket_id, after_id), page)
    return TicketMessageList(items=[message_out(m, user, presign) for m in items], meta=meta)


@router.post(
    "/tickets/{ticketId}/messages",
    operation_id="createTicketMessage",
    status_code=status.HTTP_201_CREATED,
    **rbac(*ALL_ROLES),
)
def create_ticket_message(
    ticket_id: TicketId,
    body: TicketMessageCreateRequest,
    user: CurrentUser,
    db: DbDep,
    redis: RedisDep,
    events: TicketEventsDep,
    settings: SettingsDep,
    storage: StorageDep,
    presign: PresignDep,
) -> TicketMessageOut:
    message = service.create_message(
        db,
        redis,
        events,
        settings,
        storage,
        user,
        ticket_id,
        body=body.body,
        attachment_inputs=body.attachments,
    )
    return message_out(message, user, presign)
