"""Сценарии Tickets Service (Глава 13, ADR 0017). Доступ к конкретному тикету — `access`.

Сценарии возвращают объекты со связями, загруженными для ответа (`TICKET_OUT`,
`TICKET_DETAIL`, `MESSAGE_OUT`): ленивая подгрузка в моделях запрещена (ADR 0015).
События (`events`) публикуются после COMMIT и после последнего обращения к БД в сценарии.
Описания, тексты сообщений и имена файлов в логи не пишутся (ADR 0017 п. 12).
"""

from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass

from redis import Redis
from sqlalchemy import Select, func, not_, select, update
from sqlalchemy.orm import Session, selectinload

from app.core import rate_limit
from app.core.config import Settings
from app.core.db import BIGINT_MAX
from app.core.errors import ApiError
from app.core.storage import ObjectStorage
from app.domain.aggregates.service import AggregateStatusView, current_statuses
from app.domain.tickets import access, attachments, events, sla
from app.domain.tickets.attachments import AttachmentInput
from app.domain.tickets.status import InvalidTransition, after_assignment, transition
from app.domain.vehicles import access as vehicle_access
from app.models import (
    AppUser,
    DecisionTreeNode,
    KnowledgeArticle,
    Ticket,
    TicketMessage,
    TicketSlaPolicy,
    Vehicle,
)
from app.models.enums import TicketCategory, TicketStatus, UserRole

TICKET_OUT = (selectinload(Ticket.vehicle).selectinload(Vehicle.vehicle_model),)
TICKET_DETAIL = (*TICKET_OUT, selectinload(Ticket.attachments))
MESSAGE_OUT = (selectinload(TicketMessage.author), selectinload(TicketMessage.attachments))

STAFF = frozenset({UserRole.ENGINEER, UserRole.ADMIN})


@dataclass(frozen=True)
class TicketCard:
    """Карточка тикета: тикет со связями и статусы агрегатов авто на момент обращения."""

    ticket: Ticket
    aggregate_statuses: list[AggregateStatusView]


def _card(db: Session, ticket_id: int) -> TicketCard:
    """Состояние после commit (UPDATE в обход ORM, триггеры) со связями для ответа."""
    ticket = db.get_one(Ticket, ticket_id, options=TICKET_DETAIL, populate_existing=True)
    return TicketCard(ticket, current_statuses(db, ticket.vehicle))


@contextmanager
def _counted(
    redis: Redis, key: str, window_seconds: int, limit: int, message: str
) -> Iterator[None]:
    """Лимит на созданные объекты, а не на попытки (ADR 0017 п. 7–8: «10 тикетов в час»).

    Попытка учитывается сразу (параллельные запросы не обойдут лимит), а отказ — ошибка
    проверки или сбой — возвращает её в окно: исправленный запрос клиент повторит без 429.
    Отказ 429 тоже возвращает свою попытку: счётчик = успешные + выполняющиеся.
    """
    try:
        rate_limit.enforce(redis, key, window_seconds, limit, message)
    except ApiError:
        rate_limit.undo_hit(redis, key)
        raise
    try:
        yield
    except BaseException:
        rate_limit.undo_hit(redis, key)
        raise


# ---------- Список и карточка ----------


def list_tickets_stmt(
    user: AppUser,
    *,
    status: TicketStatus | None = None,
    category: TicketCategory | None = None,
    assigned_engineer_id: int | None = None,
    overdue: bool | None = None,
) -> Select:
    """GET /tickets: фильтры сужают видимую выборку (ADR 0017 п. 3).

    Персонал — по сроку SLA (приоритет следует из категории), клиент — новые первыми.
    """
    stmt = (
        select(Ticket)
        .where(access.visible(user))
        .options(*TICKET_OUT)
        .execution_options(populate_existing=True)
    )
    if status is not None:
        stmt = stmt.where(Ticket.status == status)
    if category is not None:
        stmt = stmt.where(Ticket.category == category)
    if assigned_engineer_id is not None:
        stmt = stmt.where(Ticket.assigned_engineer_id == assigned_engineer_id)
    if overdue is not None:
        stmt = stmt.where(Ticket.is_overdue if overdue else not_(Ticket.is_overdue))
    if user.role in STAFF:
        return stmt.order_by(Ticket.sla_due_at, Ticket.id)
    return stmt.order_by(Ticket.created_at.desc(), Ticket.id.desc())


def get_ticket(db: Session, user: AppUser, ticket_id: int) -> TicketCard:
    """GET /tickets/{id}: карточка с контекстом авто (Vehicle + Aggregates, Глава 17)."""
    ticket = access.get_ticket(db, user, ticket_id, *TICKET_DETAIL)
    return TicketCard(ticket, current_statuses(db, ticket.vehicle))


# ---------- Создание ----------


def _source_error(message: str) -> ApiError:
    return ApiError(
        422,
        "INVALID_SOURCE_REFERENCE",
        message,
        details={"fields": [{"loc": ["body", "source_article_id"]}]},
    )


def _check_source(db: Session, article_id: int | None, node_id: int | None) -> None:
    """Эскалация из дерева решений: статья опубликована, узел — её (ADR 0017 п. 7).

    Тикет создаёт клиент, а черновик для клиента не существует (listArticles): черновик —
    тот же 422, что и отсутствующая статья, — ответ не раскрывает id черновиков.
    """
    if article_id is None:
        if node_id is not None:
            raise _source_error("Узел дерева решений указан без статьи")
        return
    article = db.get(KnowledgeArticle, article_id) if 1 <= article_id <= BIGINT_MAX else None
    if article is None or not article.is_published:
        raise _source_error("Статья базы знаний не найдена")
    if node_id is None:
        return
    node_article = None
    if 1 <= node_id <= BIGINT_MAX:
        node_article = db.scalar(
            select(DecisionTreeNode.article_id).where(DecisionTreeNode.id == node_id)
        )
    if node_article != article_id:
        raise _source_error("Узел дерева решений не найден в указанной статье")


def create_ticket(
    db: Session,
    redis: Redis,
    settings: Settings,
    storage: ObjectStorage,
    user: AppUser,
    *,
    vehicle_id: int,
    category: TicketCategory,
    description: str,
    source_article_id: int | None,
    source_node_id: int | None,
    attachment_inputs: Sequence[AttachmentInput],
) -> TicketCard:
    """POST /tickets (client): тикет в очереди (new без исполнителя) на своё активное авто."""
    with _counted(
        redis,
        f"ticket-create:{user.id}",
        3600,
        settings.ticket_create_per_user_hour,
        "Слишком много новых тикетов — попробуйте позже",
    ):
        ticket_id = _create_ticket(
            db,
            settings,
            storage,
            user,
            vehicle_id=vehicle_id,
            category=category,
            description=description,
            source_article_id=source_article_id,
            source_node_id=source_node_id,
            attachment_inputs=attachment_inputs,
        )
    return _card(db, ticket_id)


def _create_ticket(
    db: Session,
    settings: Settings,
    storage: ObjectStorage,
    user: AppUser,
    *,
    vehicle_id: int,
    category: TicketCategory,
    description: str,
    source_article_id: int | None,
    source_node_id: int | None,
    attachment_inputs: Sequence[AttachmentInput],
) -> int:
    # Проверки до работы с S3; авто ещё раз — под блокировкой перед записью.
    vehicle_access.get_vehicle(db, user, vehicle_id)  # чужое или удалённое — 404
    _check_source(db, source_article_id, source_node_id)
    uploads = attachments.check_uploads(db, storage, settings, user, attachment_inputs)
    # id тикета выдаётся заранее: вложения копируются в tickets/{id}/ до записи и блокировок.
    ticket_id = db.scalar(select(func.nextval(func.pg_get_serial_sequence("ticket", "id"))))

    with attachments.binding(db, storage) as copied:
        keys = attachments.copy_uploads(storage, uploads, copied, ticket_id=ticket_id)
        vehicle = vehicle_access.for_new_ticket(db, user, vehicle_id)
        # created_at — момент записи (после блокировки авто), а не начало транзакции запроса;
        # срок SLA, updated_at и created_at вложений — от того же значения.
        now, minutes = db.execute(
            select(func.clock_timestamp(), TicketSlaPolicy.resolution_minutes).where(
                TicketSlaPolicy.category == category
            )
        ).one()
        db.add(
            Ticket(
                id=ticket_id,
                vehicle_id=vehicle.id,
                category=category,
                status=TicketStatus.NEW,
                description=description,
                created_at=now,
                updated_at=now,
                sla_due_at=sla.due_at(now, minutes),
                firmware_release_id=vehicle.current_firmware_release_id,  # снимок (N-09)
                source_article_id=source_article_id,
                source_node_id=source_node_id,
            )
        )
        db.flush()
        attachments.add_rows(db, user, uploads, keys, ticket_id=ticket_id, created_at=now)
        db.commit()
    attachments.discard_uploads(storage, uploads)
    return ticket_id


# ---------- Статус, claim, назначение ----------


def change_status(
    db: Session, redis: Redis, user: AppUser, ticket_id: int, target: TicketStatus
) -> TicketCard:
    """PATCH /tickets/{id}/status (engineer/admin) по графу `status.TRANSITIONS`."""
    ticket = access.for_update(db, user, ticket_id)
    access.ensure_can_change_status(user, ticket)
    # Момент записи под блокировкой (clock_timestamp), а не начало транзакции запроса (now()):
    # сообщение, принятое до решения, не окажется датировано позже resolved_at.
    now = db.scalar(select(func.clock_timestamp()))
    try:
        change = transition(ticket.status, target, ticket.resolved_at, now)
    except InvalidTransition as exc:
        raise ApiError(
            409,
            "INVALID_STATUS_TRANSITION",
            f"Переход {exc.current} → {exc.target} недопустим",
            details={"from": exc.current, "to": exc.target},
        ) from exc
    if change is not None:
        ticket.status = change.status
        ticket.resolved_at = change.resolved_at
    db.commit()  # и без изменений — снимает блокировку строки
    card = _card(db, ticket.id)
    if change is not None:
        events.ticket_updated(redis, ticket.id)
    return card


def claim_ticket(db: Session, redis: Redis, user: AppUser, ticket_id: int) -> TicketCard:
    """POST /tickets/{id}/claim (engineer): атомарное самоназначение из очереди (ADR 0017 п. 5).

    UPDATE с условием «в очереди» — проигравший гонку не перезапишет победителя: строка
    заблокирована до commit первого, после чего условие для второго уже ложно.
    """
    if not access.in_range(ticket_id):
        raise access.not_found()
    claimed = db.scalar(
        update(Ticket)
        .where(
            Ticket.id == ticket_id,
            Ticket.assigned_engineer_id.is_(None),
            Ticket.status == TicketStatus.NEW,
        )
        .values(assigned_engineer_id=user.id, status=TicketStatus.IN_PROGRESS)
        .returning(Ticket.id)
        .execution_options(synchronize_session=False)
    )
    if claimed is None:
        assignee_id = db.scalar(select(Ticket.assigned_engineer_id).where(Ticket.id == ticket_id))
        db.rollback()
        if assignee_id is None:  # нет тикета или он не в очереди и не назначен — невидим
            raise access.not_found()
        if assignee_id != user.id:
            # Контракт claimTicket: «уже у другого инженера» — 409, а не 404 (ADR 0017 п. 5).
            raise ApiError(409, "TICKET_ALREADY_CLAIMED", "Тикет уже взят другим инженером")
    else:
        db.commit()
    card = _card(db, ticket_id)
    if claimed is not None:
        events.ticket_updated(redis, ticket_id)
    return card


def _assignee(db: Session, engineer_id: int) -> AppUser:
    engineer = db.get(AppUser, engineer_id) if 1 <= engineer_id <= BIGINT_MAX else None
    if (
        engineer is None
        or engineer.role is not UserRole.ENGINEER
        or not engineer.is_active
        or engineer.anonymized_at is not None
    ):
        raise ApiError(
            422,
            "ASSIGNEE_NOT_ENGINEER",
            "Назначить можно только активного инженера",
            details={"fields": [{"loc": ["body", "assigned_engineer_id"]}]},
        )
    return engineer


def assign_ticket(
    db: Session, redis: Redis, user: AppUser, ticket_id: int, engineer_id: int | None
) -> TicketCard:
    """PATCH /tickets/{id}/assign (admin): назначение, переназначение, снятие (ADR 0017 п. 5)."""
    ticket = access.for_update(db, user, ticket_id)
    if ticket.status is TicketStatus.RESOLVED:
        raise access.ticket_resolved()
    if engineer_id is not None:
        _assignee(db, engineer_id)
    new_status = after_assignment(ticket.status, engineer_id)
    changed = (ticket.assigned_engineer_id, ticket.status) != (engineer_id, new_status)
    if changed:
        ticket.assigned_engineer_id = engineer_id
        ticket.status = new_status
    db.commit()
    card = _card(db, ticket.id)
    if changed:
        # Подключения WebSocket, потерявшие доступ, закроются 4403 при обработке события.
        events.ticket_updated(redis, ticket.id)
    return card


# ---------- Чат ----------


def list_messages_stmt(db: Session, user: AppUser, ticket_id: int, after_id: int | None) -> Select:
    """GET /tickets/{id}/messages: по id по возрастанию; after_id — догрузка (ADR 0017 п. 8)."""
    access.get_ticket(db, user, ticket_id)
    stmt = (
        select(TicketMessage)
        .where(TicketMessage.ticket_id == ticket_id)
        .order_by(TicketMessage.id)
        .options(*MESSAGE_OUT)
    )
    if after_id is not None:
        stmt = stmt.where(TicketMessage.id > after_id)
    return stmt


def get_message(db: Session, ticket_id: int, message_id: int) -> TicketMessage | None:
    """Сообщение тикета со связями — для события message.created (доступ проверен ранее)."""
    return db.scalars(
        select(TicketMessage)
        .where(TicketMessage.id == message_id, TicketMessage.ticket_id == ticket_id)
        .options(*MESSAGE_OUT)
    ).one_or_none()


def create_message(
    db: Session,
    redis: Redis,
    settings: Settings,
    storage: ObjectStorage,
    user: AppUser,
    ticket_id: int,
    *,
    body: str,
    attachment_inputs: Sequence[AttachmentInput],
) -> TicketMessage:
    """POST /tickets/{id}/messages — единственный путь записи в чат (WebSocket — доставка)."""
    with _counted(
        redis,
        f"ticket-message:{user.id}",
        60,
        settings.ticket_message_per_user_minute,
        "Слишком много сообщений — подождите немного",
    ):
        message_id = _create_message(
            db, settings, storage, user, ticket_id, body=body, attachment_inputs=attachment_inputs
        )
    message = db.get_one(TicketMessage, message_id, options=MESSAGE_OUT, populate_existing=True)
    events.message_created(redis, message.ticket_id, message.id)
    return message


def _create_message(
    db: Session,
    settings: Settings,
    storage: ObjectStorage,
    user: AppUser,
    ticket_id: int,
    *,
    body: str,
    attachment_inputs: Sequence[AttachmentInput],
) -> int:
    # Проверки до работы с S3 — без блокировки; под блокировкой строки тикета они повторяются,
    # а сетевой ввод-вывод S3 (HEAD, копирование) её не держит.
    ticket = access.get_ticket(db, user, ticket_id)
    access.ensure_can_write_message(user, ticket)
    uploads = attachments.check_uploads(db, storage, settings, user, attachment_inputs)

    with attachments.binding(db, storage) as copied:
        keys = attachments.copy_uploads(storage, uploads, copied, ticket_id=ticket.id)
        ticket = access.for_update(db, user, ticket_id)
        access.ensure_can_write_message(user, ticket)
        # Момент записи под блокировкой: в чате тикета created_at растёт вместе с id и не
        # позже resolved_at (решение ждёт ту же блокировку).
        now = db.scalar(select(func.clock_timestamp()))
        message = TicketMessage(ticket_id=ticket.id, author_id=user.id, body=body, created_at=now)
        db.add(message)
        db.flush()
        attachments.add_rows(
            db,
            user,
            uploads,
            keys,
            ticket_id=ticket.id,
            created_at=now,
            ticket_message_id=message.id,
        )
        if user.role in STAFF:
            # Первичный ответ — однократно (метрика аналитики, ADR 0017 п. 1).
            db.execute(
                update(Ticket)
                .where(Ticket.id == ticket.id, Ticket.first_response_at.is_(None))
                .values(first_response_at=now)
                .execution_options(synchronize_session=False)
            )
        db.commit()
    attachments.discard_uploads(storage, uploads)
    return message.id
