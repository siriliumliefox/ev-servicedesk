"""Сценарии Tickets Service (Глава 13, ADR 0017). Доступ к конкретному тикету — `access`.

Сценарии возвращают объекты со связями, загруженными для ответа (`TICKET_OUT`,
`TICKET_DETAIL`, `MESSAGE_OUT`): ленивая подгрузка в моделях запрещена (ADR 0015).
События (`events`) публикуются после COMMIT и после последнего обращения к БД в сценарии.
Описания, тексты сообщений и имена файлов в логи не пишутся (ADR 0017 п. 12).
Создание тикета и сообщения повторяемо по ключу `client_request_id` (ADR 0031).
"""

import uuid
from collections.abc import Sequence
from datetime import datetime

from redis import Redis
from sqlalchemy import Select, func, not_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from app.core import rate_limit
from app.core.config import Settings
from app.core.db import constraint_name, get_by_id, is_db_id
from app.core.errors import ApiError, field_error
from app.core.storage import ObjectStorage
from app.domain.aggregates.service import current_statuses
from app.domain.knowledge import service as knowledge
from app.domain.tickets import access, attachments, sla
from app.domain.tickets.attachments import AttachmentInput
from app.domain.tickets.card import TicketCard
from app.domain.tickets.events import TicketEvents
from app.domain.tickets.status import InvalidTransition, after_assignment, transition
from app.domain.vehicles import access as vehicle_access
from app.models import (
    AppUser,
    Ticket,
    TicketMessage,
    TicketSlaPolicy,
    Vehicle,
)
from app.models.enums import STAFF_ROLES, TicketCategory, TicketStatus, UserRole

TICKET_OUT = (selectinload(Ticket.vehicle).selectinload(Vehicle.vehicle_model),)
TICKET_DETAIL = (
    *TICKET_OUT,
    selectinload(Ticket.attachments),
    selectinload(Ticket.source_article),
)
MESSAGE_OUT = (selectinload(TicketMessage.author), selectinload(TicketMessage.attachments))


def _card(db: Session, ticket_id: int) -> TicketCard:
    """Состояние после commit (UPDATE в обход ORM, триггеры) со связями для ответа."""
    ticket = db.get_one(Ticket, ticket_id, options=TICKET_DETAIL, populate_existing=True)
    return TicketCard(ticket, current_statuses(db, ticket.vehicle))


def _finish(db: Session, events: TicketEvents, ticket_id: int, *, changed: bool) -> TicketCard:
    """Конец записи тикета: commit → карточка → событие, если тикет изменился.

    Commit и без изменений — снимает блокировку строки. Событие — после COMMIT и после
    последнего обращения к БД (подписчик перечитает уже записанное состояние).
    """
    db.commit()
    card = _card(db, ticket_id)
    if changed:
        events.ticket_updated(ticket_id)
    return card


# ---------- Повтор запроса (ADR 0031) ----------


class _AlreadyCreated(Exception):
    """Повтор дождался блокировки исходного запроса и нашёл под ней запись со своим ключом."""

    def __init__(self, record_id: int) -> None:
        super().__init__(record_id)
        self.record_id = record_id


def _key_reused() -> ApiError:
    return field_error(
        "client_request_id",
        "CLIENT_REQUEST_ID_REUSED",
        "Ключ повтора уже использован для другого запроса — создайте новый",
    )


def _created_ticket_id(
    db: Session,
    user: AppUser,
    vehicle_id: int,
    key: uuid.UUID | None,
    category: TicketCategory,
    description: str,
) -> int | None:
    """Тикет, уже созданный на видимое авто с ключом `key`; тот же ключ, другой тикет — 422."""
    if key is None or not is_db_id(vehicle_id):
        return None
    row = db.execute(
        select(Ticket.id, Ticket.category, Ticket.description).where(
            Ticket.vehicle_id == vehicle_id, Ticket.client_request_id == key, access.visible(user)
        )
    ).one_or_none()
    if row is None:
        return None
    if (row.category, row.description) != (category, description):
        raise _key_reused()
    return row.id


def _sent_message_id(
    db: Session, user: AppUser, ticket_id: int, key: uuid.UUID | None, body: str
) -> int | None:
    """Сообщение автора `user` с ключом `key` в видимом тикете; тот же ключ, другой текст — 422."""
    if key is None or not is_db_id(ticket_id):
        return None
    row = db.execute(
        select(TicketMessage.id, TicketMessage.body)
        .join(Ticket, Ticket.id == TicketMessage.ticket_id)
        .where(
            TicketMessage.ticket_id == ticket_id,
            TicketMessage.author_id == user.id,
            TicketMessage.client_request_id == key,
            access.visible(user),
        )
    ).one_or_none()
    if row is None:
        return None
    if row.body != body:
        raise _key_reused()
    return row.id


# ---------- Список и карточка ----------


def list_tickets_stmt(
    user: AppUser,
    *,
    status: TicketStatus | None = None,
    category: TicketCategory | None = None,
    assigned_engineer_id: int | None = None,
    overdue: bool | None = None,
    resolved_since: datetime | None = None,
) -> Select:
    """GET /tickets: фильтры сужают видимую выборку (ADR 0017 п. 3).

    `resolved_since` — решённые не раньше момента (колонка «Решено», ADR 0025 п. 9); у
    переоткрытого тикета `resolved_at` сброшен, он в выборку не попадает.

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
    if resolved_since is not None:
        stmt = stmt.where(Ticket.resolved_at >= resolved_since)
    if user.role in STAFF_ROLES:
        return stmt.order_by(Ticket.sla_due_at, Ticket.id)
    return stmt.order_by(Ticket.created_at.desc(), Ticket.id.desc())


def get_ticket(db: Session, user: AppUser, ticket_id: int) -> TicketCard:
    """GET /tickets/{id}: карточка с контекстом авто (Vehicle + Aggregates, Глава 17)."""
    ticket = access.get_ticket(db, user, ticket_id, *TICKET_DETAIL)
    return TicketCard(ticket, current_statuses(db, ticket.vehicle))


# ---------- Создание ----------


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
    client_request_id: uuid.UUID | None = None,
) -> TicketCard:
    """POST /tickets (client): тикет в очереди (new без исполнителя) на своё активное авто.

    Повтор с ключом `client_request_id` (ADR 0031) возвращает тикет, уже созданный с этим
    ключом на это авто, — без новой записи и без учёта в лимите.
    """
    key = client_request_id

    def created() -> int | None:
        return _created_ticket_id(db, user, vehicle_id, key, category, description)

    ticket_id = created()
    if ticket_id is not None:
        return _card(db, ticket_id)
    try:
        ticket_id = _write_ticket(
            db,
            redis,
            settings,
            storage,
            user,
            vehicle_id=vehicle_id,
            category=category,
            description=description,
            source_article_id=source_article_id,
            source_node_id=source_node_id,
            attachment_inputs=attachment_inputs,
            client_request_id=key,
        )
    except IntegrityError as exc:
        # Одновременный повтор: FOR SHARE авто запросы не упорядочивает, вставку второго
        # останавливает UNIQUE ключа до commit первого — тогда записанное уже видно.
        if constraint_name(exc) != "uq_ticket_vehicle_id_client_request_id":
            raise
        ticket_id = created()
        if ticket_id is None:
            raise
    except ApiError:
        # Повтор, начатый до commit исходного запроса: исходный уже привязал вложения и
        # удалил загрузки — 422 ATTACHMENT_NOT_FOUND повтору не ошибка.
        ticket_id = created()
        if ticket_id is None:
            raise
    return _card(db, ticket_id)


def _write_ticket(
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
    client_request_id: uuid.UUID | None,
) -> int:
    with rate_limit.reserve(
        redis,
        f"ticket-create:{user.id}",
        3600,
        settings.ticket_create_per_user_hour,
        "Слишком много новых тикетов — попробуйте позже",
    ):
        # Проверки до работы с S3; авто ещё раз — под блокировкой перед записью.
        vehicle_access.get_vehicle(db, user, vehicle_id)  # чужое или удалённое — 404
        # Эскалация из дерева решений — версия статьи для «пометки» (ADR 0018 п. 11).
        source_version = knowledge.escalation_version(db, source_article_id, source_node_id)
        uploads = attachments.check_uploads(db, storage, settings, user, attachment_inputs)
        # id тикета выдаётся заранее: вложения копируются в tickets/{id}/ до записи и блокировок.
        ticket_id = db.scalar(select(func.nextval(func.pg_get_serial_sequence("ticket", "id"))))

        # Commit — при выходе из блока (attachments.bind).
        with attachments.bind(db, storage, user, uploads, ticket_id=ticket_id) as attach:
            vehicle = vehicle_access.for_new_ticket(db, user, vehicle_id)
            # created_at — момент записи (после блокировки авто), а не начало транзакции
            # запроса; срок SLA, updated_at и created_at вложений — от того же значения.
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
                    source_article_version=source_version,
                    source_node_id=source_node_id,
                    client_request_id=client_request_id,
                )
            )
            db.flush()
            attach(created_at=now)
    return ticket_id


# ---------- Статус, claim, назначение ----------


def change_status(
    db: Session, events: TicketEvents, user: AppUser, ticket_id: int, target: TicketStatus
) -> TicketCard:
    """PATCH /tickets/{id}/status (engineer/admin) по графу `status.TRANSITIONS`."""
    ticket = access.for_update(db, user, ticket_id)
    access.ensure_can_change_status(user, ticket)
    # Момент записи под блокировкой (clock_timestamp), а не начало транзакции запроса (now()):
    # сообщение, принятое до решения, не окажется датировано позже resolved_at.
    now = db.scalar(select(func.clock_timestamp()))
    try:
        ticket.status, ticket.resolved_at = transition(
            ticket.status, target, ticket.resolved_at, now
        )
    except InvalidTransition as exc:
        raise ApiError(
            409,
            "INVALID_STATUS_TRANSITION",
            f"Переход {exc.current} → {exc.target} недопустим",
            details={"from": exc.current, "to": exc.target},
        ) from exc
    # Присвоение равного значения изменением не считается: запрошен текущий статус — без события.
    return _finish(db, events, ticket.id, changed=db.is_modified(ticket))


def claim_ticket(db: Session, events: TicketEvents, user: AppUser, ticket_id: int) -> TicketCard:
    """POST /tickets/{id}/claim (engineer): атомарное самоназначение из очереди (ADR 0017 п. 5).

    UPDATE с условием «в очереди» — проигравший гонку не перезапишет победителя: строка
    заблокирована до commit первого, после чего условие для второго уже ложно.
    """
    if not is_db_id(ticket_id):
        raise access.not_found()
    claimed = db.scalar(
        update(Ticket)
        .where(Ticket.id == ticket_id, access.in_queue())
        .values(assigned_engineer_id=user.id, status=TicketStatus.IN_PROGRESS)
        .returning(Ticket.id)
        .execution_options(synchronize_session=False)
    )
    if claimed is None:
        assignee_id = db.scalar(select(Ticket.assigned_engineer_id).where(Ticket.id == ticket_id))
        if assignee_id is None:  # нет тикета или он не в очереди и не назначен — невидим
            raise access.not_found()
        if assignee_id != user.id:
            # Контракт claimTicket: «уже у другого инженера» — 409, а не 404 (ADR 0017 п. 5).
            raise ApiError(409, "TICKET_ALREADY_CLAIMED", "Тикет уже взят другим инженером")
    # Уже свой — повтор без изменений: UPDATE ничего не записал, commit только завершает чтение.
    return _finish(db, events, ticket_id, changed=claimed is not None)


def _assignee(db: Session, engineer_id: int) -> AppUser:
    engineer = get_by_id(db, AppUser, engineer_id)
    if engineer is None or engineer.role is not UserRole.ENGINEER or not engineer.is_available:
        raise field_error(
            "assigned_engineer_id",
            "ASSIGNEE_NOT_ENGINEER",
            "Назначить можно только активного инженера",
        )
    return engineer


def assign_ticket(
    db: Session, events: TicketEvents, user: AppUser, ticket_id: int, engineer_id: int | None
) -> TicketCard:
    """PATCH /tickets/{id}/assign (admin): назначение, переназначение, снятие (ADR 0017 п. 5)."""
    ticket = access.for_update(db, user, ticket_id)
    if ticket.status is TicketStatus.RESOLVED:
        raise access.ticket_resolved()
    if engineer_id is not None:
        _assignee(db, engineer_id)
    ticket.status = after_assignment(ticket.status, engineer_id)
    ticket.assigned_engineer_id = engineer_id
    # Подключения WebSocket, потерявшие доступ, закроются 4403 при обработке события.
    return _finish(db, events, ticket.id, changed=db.is_modified(ticket))


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
    events: TicketEvents,
    settings: Settings,
    storage: ObjectStorage,
    user: AppUser,
    ticket_id: int,
    *,
    body: str,
    attachment_inputs: Sequence[AttachmentInput],
    client_request_id: uuid.UUID | None = None,
) -> TicketMessage:
    """POST /tickets/{id}/messages — единственный путь записи в чат (WebSocket — доставка).

    Повтор с ключом `client_request_id` (ADR 0031) возвращает сообщение, уже записанное с этим
    ключом тем же автором в тот же тикет, — без новой записи, без события message.created и
    без учёта в лимите. Решённый после записи тикет повтору не мешает.
    """
    key = client_request_id

    def sent() -> int | None:
        return _sent_message_id(db, user, ticket_id, key, body)

    message_id = sent()
    created = False
    if message_id is None:
        try:
            message_id = _write_message(
                db,
                redis,
                settings,
                storage,
                user,
                ticket_id,
                body=body,
                attachment_inputs=attachment_inputs,
                client_request_id=key,
            )
            created = True
        except _AlreadyCreated as exc:
            message_id = exc.record_id
        except ApiError:
            # Повтор, начатый до commit исходного запроса: исходный уже привязал вложения и
            # удалил загрузки — 422 ATTACHMENT_NOT_FOUND повтору не ошибка.
            message_id = sent()
            if message_id is None:
                raise
    message = db.get_one(TicketMessage, message_id, options=MESSAGE_OUT, populate_existing=True)
    if created:
        events.message_created(message.ticket_id, message.id)
    return message


def _write_message(
    db: Session,
    redis: Redis,
    settings: Settings,
    storage: ObjectStorage,
    user: AppUser,
    ticket_id: int,
    *,
    body: str,
    attachment_inputs: Sequence[AttachmentInput],
    client_request_id: uuid.UUID | None,
) -> int:
    with rate_limit.reserve(
        redis,
        f"ticket-message:{user.id}",
        60,
        settings.ticket_message_per_user_minute,
        "Слишком много сообщений — подождите немного",
    ):
        # Проверки до работы с S3 — без блокировки; под блокировкой строки тикета они
        # повторяются, а сетевой ввод-вывод S3 (HEAD, копирование) её не держит.
        ticket = access.get_ticket(db, user, ticket_id)
        access.ensure_can_write_message(user, ticket)
        uploads = attachments.check_uploads(db, storage, settings, user, attachment_inputs)

        # Commit — при выходе из блока (attachments.bind).
        with attachments.bind(db, storage, user, uploads, ticket_id=ticket.id) as attach:
            ticket = access.for_update(db, user, ticket_id)
            # Повторы с одним ключом идут по очереди этой блокировки: второй видит запись
            # первого и откатывает свою попытку (копии вложений удаляет bind).
            sent = _sent_message_id(db, user, ticket.id, client_request_id, body)
            if sent is not None:
                raise _AlreadyCreated(sent)
            access.ensure_can_write_message(user, ticket)
            # Момент записи под блокировкой: в чате тикета created_at растёт вместе с id и не
            # позже resolved_at (решение ждёт ту же блокировку).
            now = db.scalar(select(func.clock_timestamp()))
            message = TicketMessage(
                ticket_id=ticket.id,
                author_id=user.id,
                body=body,
                created_at=now,
                client_request_id=client_request_id,
            )
            db.add(message)
            db.flush()
            attach(created_at=now, ticket_message_id=message.id)
            if user.role in STAFF_ROLES:
                # Первичный ответ — однократно (метрика аналитики, ADR 0017 п. 1).
                db.execute(
                    update(Ticket)
                    .where(Ticket.id == ticket.id, Ticket.first_response_at.is_(None))
                    .values(first_response_at=now)
                    .execution_options(synchronize_session=False)
                )
    return message.id
