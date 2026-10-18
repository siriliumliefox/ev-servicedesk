"""Анонимизация ПД после отзыва согласия и сроки хранения (99-З ст. 10 п. 2, ст. 4 п. 8;
ADR 0013 п. 9, ADR 0029 пп. 18–19; глоссарий «Анонимизация», «Срок хранения данных»).

Очередь — клиенты без действующего согласия по последнему `withdrawn_at` (строку с
`withdrawn_at` получает и согласие, заменённое новой редакцией, — такой клиент не в очереди).
Анонимизация клиента — одна транзакция под блокировкой пользователя:
- `app_user`: телефон и Telegram — NULL, `anonymized_at`;
- авто: мягко удаляются, VIN → 17 нулей (`vehicle_guard` разрешает это только удалённому авто);
- тикеты его авто: описание и тексты всех сообщений → отметка удаления, открытые → `resolved`;
  вложения: объекты S3 удаляются ДО COMMIT (сбой S3 — откат, повтор при следующем проходе;
  удаление отсутствующего объекта в S3 не ошибка), строки — в той же транзакции;
- push-токены (с доставками), входящие уведомления, refresh-токены — удаляются;
- `pd_consent` сохраняется — доказательство согласия (ст. 5 п. 7), история ТО и статусы
  тикетов — обезличенно (идентификаторы без ПД).
"""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import ColumnElement, Select, and_, delete, exists, func, or_, select, update
from sqlalchemy.orm import Session

from app.core.storage import ObjectStorage
from app.domain.auth import tokens
from app.models import (
    AppUser,
    NotificationDelivery,
    NotificationRecipient,
    PdConsent,
    PushToken,
    RefreshToken,
    Ticket,
    TicketAttachment,
    TicketMessage,
    Vehicle,
)
from app.models.enums import TicketStatus, UserRole

ANONYMIZED_VIN = "0" * 17
REDACTED = "Удалено по запросу клиента (99-З)"
DEADLINE = timedelta(days=15)  # ст. 10 п. 2: пятнадцатидневный срок
LATE = timedelta(days=14)  # клиент в очереди дольше — ERROR в лог: срок под угрозой
TOKEN_RETENTION = timedelta(days=30)  # отозванные и истёкшие refresh- и push-токены
DELIVERY_RETENTION = timedelta(days=180)  # журнал доставок push


@dataclass(frozen=True)
class Due:
    user_id: int
    phone: str | None
    withdrawn_at: datetime


def _no_active_consent() -> ColumnElement[bool]:
    return ~exists().where(PdConsent.user_id == AppUser.id, PdConsent.withdrawn_at.is_(None))


def due_stmt(limit: int | None = 100) -> Select[tuple[int, str | None, datetime]]:
    """Очередь анонимизации: давние отзывы — первыми."""
    withdrawn = (
        select(func.max(PdConsent.withdrawn_at))
        .where(PdConsent.user_id == AppUser.id)
        .correlate(AppUser)
        .scalar_subquery()
    )
    return (
        select(AppUser.id, AppUser.phone, withdrawn.label("withdrawn_at"))
        .where(
            AppUser.role == UserRole.CLIENT,
            AppUser.anonymized_at.is_(None),
            _no_active_consent(),
            withdrawn.is_not(None),
        )
        .order_by(withdrawn, AppUser.id)
        .limit(limit)
    )


def due(db: Session, limit: int = 100) -> list[Due]:
    return [Due(*row) for row in db.execute(due_stmt(limit)).all()]


def queue_stats(db: Session) -> tuple[int, datetime | None]:
    """Размер очереди анонимизации и самый ранний отзыв в ней (метрики, глава 26)."""
    queue = due_stmt(limit=None).order_by(None).subquery()
    count, oldest = db.execute(select(func.count(), func.min(queue.c.withdrawn_at))).one()
    return count, oldest


def anonymize(db: Session, storage: ObjectStorage, user_id: int, now: datetime) -> bool:
    """Анонимизирует клиента одной транзакцией; False — уже не в очереди (снова дал согласие,
    анонимизирован параллельно)."""
    tokens.lock_user(db, user_id)
    user = db.get(AppUser, user_id, populate_existing=True)
    still_due = db.scalar(select(_no_active_consent()).where(AppUser.id == user_id))
    if user is None or user.anonymized_at is not None or not still_due:
        db.rollback()
        return False

    ticket_ids = (
        select(Ticket.id)
        .join(Vehicle, Vehicle.id == Ticket.vehicle_id)
        .where(Vehicle.user_id == user_id)
    )
    keys = db.scalars(
        select(TicketAttachment.object_key).where(TicketAttachment.ticket_id.in_(ticket_ids))
    ).all()
    for key in keys:  # до COMMIT: сбой S3 откатывает транзакцию, проход повторится
        storage.delete(key)
    db.execute(delete(TicketAttachment).where(TicketAttachment.ticket_id.in_(ticket_ids)))
    db.execute(
        update(TicketMessage).where(TicketMessage.ticket_id.in_(ticket_ids)).values(body=REDACTED)
    )
    db.execute(
        update(Ticket)
        .where(Ticket.id.in_(ticket_ids))
        .values(
            description=REDACTED,
            status=TicketStatus.RESOLVED,
            resolved_at=func.coalesce(Ticket.resolved_at, now),
        )
        .execution_options(synchronize_session=False)
    )
    db.execute(
        update(Vehicle)
        .where(Vehicle.user_id == user_id)
        .values(vin=ANONYMIZED_VIN, deleted_at=func.coalesce(Vehicle.deleted_at, now))
        .execution_options(synchronize_session=False)
    )
    db.execute(delete(PushToken).where(PushToken.user_id == user_id))  # доставки — CASCADE
    db.execute(delete(NotificationRecipient).where(NotificationRecipient.user_id == user_id))
    db.execute(delete(RefreshToken).where(RefreshToken.user_id == user_id))
    user.phone = None
    user.telegram_id = None
    user.anonymized_at = now
    db.commit()
    return True


@dataclass(frozen=True)
class Purged:
    refresh_tokens: int
    push_tokens: int
    deliveries: int


def purge_expired(db: Session, now: datetime | None = None) -> Purged:
    """Сроки хранения (ADR 0029 п. 19): отозванные и истёкшие токены, давний журнал доставок."""
    now = now or datetime.now(UTC)
    token_cutoff = now - TOKEN_RETENTION
    refresh = db.execute(
        delete(RefreshToken).where(
            or_(RefreshToken.revoked_at < token_cutoff, RefreshToken.expires_at < token_cutoff)
        )
    ).rowcount
    push = db.execute(
        delete(PushToken).where(
            and_(PushToken.revoked_at.is_not(None), PushToken.revoked_at < token_cutoff)
        )
    ).rowcount
    deliveries = db.execute(
        delete(NotificationDelivery).where(
            NotificationDelivery.created_at < now - DELIVERY_RETENTION
        )
    ).rowcount
    db.commit()
    return Purged(refresh, push, deliveries)
