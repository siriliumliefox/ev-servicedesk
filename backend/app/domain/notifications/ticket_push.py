"""Push клиенту по событиям тикета (ADR 0019 п. 13, ADR 0017 п. 9, 12).

Источник — события Tickets в Redis (`{prefix}:ticket:{id}`), Tickets не меняется. Push без
записи в ленте и журнале доставок; текст — номер обращения и статус, без содержимого
сообщения (ПД, ADR 0019 п. 11).

- `message.created` от персонала → «Новое сообщение по обращению №N»; сообщения клиента push
  не вызывают. Повтор события (несколько реплик worker) отсекает ключ Redis `SET NX`.
- `ticket.updated` → push, только если статус отличается от последнего отправленного (ключ
  Redis с прежним статусом, `SET ... GET` атомарно); переход из «Нового» в первый раз — тоже.
"""

from dataclasses import dataclass
from datetime import UTC, datetime

from redis import Redis
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.notifications.push import Outcome, PushMessage, PushSender
from app.domain.notifications.service import active_tokens, eligible_client
from app.domain.tickets.events import MessageCreated, TicketUpdated
from app.models import AppUser, Ticket, TicketMessage, Vehicle
from app.models.enums import TicketStatus

TITLE = "Поддержка"
STATUS_LABELS = {
    TicketStatus.NEW: "новое",
    TicketStatus.IN_PROGRESS: "в работе",
    TicketStatus.WAITING_VENDOR: "ожидает поставщика",
    TicketStatus.RESOLVED: "решено",
}
# Дольше жизни обращения: без ключа первое событие «не нового» тикета считается сменой статуса
# (ADR 0019, уточнения) — лишний push возможен только для тикетов старше срока ключа.
DEDUP_TTL_SECONDS = 400 * 24 * 3600


@dataclass(frozen=True)
class TicketPush:
    redis: Redis
    prefix: str
    sender: PushSender

    def _key(self, kind: str, ident: int) -> str:
        return f"{self.prefix}:push:{kind}:{ident}"

    def handle(self, db: Session, event: MessageCreated | TicketUpdated) -> int:
        """Возвращает число отправленных push (0 — событие не для клиента или повтор)."""
        row = db.execute(
            select(Ticket, Vehicle.user_id)
            .join(Vehicle, Vehicle.id == Ticket.vehicle_id)
            # Тикет удалённого авто клиенту не виден (404) — и push по нему не идёт (ADR 0021 п. 5).
            .where(Ticket.id == event.ticket_id, Vehicle.deleted_at.is_(None))
        ).one_or_none()
        if row is None:
            return 0
        ticket, client_id = row
        if isinstance(event, MessageCreated):
            body = self._message_body(db, ticket, client_id, event.message_id)
        else:
            body = self._status_body(ticket)
        if body is None:
            return 0
        return self._send(db, client_id, body, ticket.id)

    def _message_body(
        self, db: Session, ticket: Ticket, client_id: int, message_id: int
    ) -> str | None:
        author_id = db.scalar(
            select(TicketMessage.author_id).where(
                TicketMessage.id == message_id, TicketMessage.ticket_id == ticket.id
            )
        )
        if author_id is None or author_id == client_id:
            return None
        key = self._key("ticket-message", message_id)
        if not self.redis.set(key, 1, nx=True, ex=DEDUP_TTL_SECONDS):
            return None
        return f"Новое сообщение по обращению №{ticket.id}"

    def _status_body(self, ticket: Ticket) -> str | None:
        status = ticket.status.value
        previous = self.redis.set(
            self._key("ticket-status", ticket.id), status, get=True, ex=DEDUP_TTL_SECONDS
        )
        if previous == status or (previous is None and ticket.status is TicketStatus.NEW):
            return None
        return f"Статус обращения №{ticket.id}: {STATUS_LABELS[ticket.status]}"

    def _send(self, db: Session, client_id: int, body: str, ticket_id: int) -> int:
        allowed = db.scalar(select(AppUser.id).where(AppUser.id == client_id, *eligible_client()))
        if allowed is None:
            return 0
        sent = 0
        for token in active_tokens(db, client_id):
            result = self.sender.send(
                PushMessage(
                    token.token, TITLE, body, {"type": "ticket", "ticket_id": str(ticket_id)}
                ),
            )
            if result.outcome is Outcome.SENT:
                sent += 1
            elif result.outcome is Outcome.INVALID_TOKEN:
                token.revoked_at = datetime.now(UTC)
        db.commit()
        return sent
