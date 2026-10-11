"""События тикета в Redis pub/sub, канал `ticket:{id}` (ADR 0017 п. 9, docs/asyncapi.yaml).

Публикуются после COMMIT и содержат только идентификаторы: `{"type", "ticket_id",
"message_id"?}`. Данные события каждое WebSocket-подключение читает из БД и формирует для
своего получателя по правилам REST (ПД сотрудника скрыты от клиента, presigned GET для
вложений) — так ПД не попадают в Redis, а доступ проверяется заново на каждом событии.
Те же события может слушать push (глава 15) без изменений Tickets. Доставка at-most-once:
сбой публикации не отменяет записанное — клиент догружает через `after_id`.
"""

import json
import logging
from dataclasses import dataclass
from enum import StrEnum

from redis import Redis
from redis.exceptions import RedisError

logger = logging.getLogger(__name__)


class EventType(StrEnum):
    MESSAGE_CREATED = "message.created"
    TICKET_UPDATED = "ticket.updated"


@dataclass(frozen=True)
class TicketEvent:
    type: EventType
    ticket_id: int
    message_id: int | None = None


def channel(ticket_id: int) -> str:
    return f"ticket:{ticket_id}"


def publish(redis: Redis, event: TicketEvent) -> None:
    payload = {"type": event.type.value, "ticket_id": event.ticket_id}
    if event.message_id is not None:
        payload["message_id"] = event.message_id
    try:
        redis.publish(channel(event.ticket_id), json.dumps(payload))
    except RedisError as exc:
        logger.warning("Событие тикета не опубликовано: %s", type(exc).__name__)


def message_created(redis: Redis, ticket_id: int, message_id: int) -> None:
    publish(redis, TicketEvent(EventType.MESSAGE_CREATED, ticket_id, message_id))


def ticket_updated(redis: Redis, ticket_id: int) -> None:
    publish(redis, TicketEvent(EventType.TICKET_UPDATED, ticket_id))


def parse(raw: str | bytes) -> TicketEvent | None:
    """Событие из канала; чужой или повреждённый формат — None (пропускается)."""
    try:
        data = json.loads(raw)
        event_type = EventType(data["type"])
        ticket_id = data["ticket_id"]
        message_id = data.get("message_id")
    except (ValueError, TypeError, KeyError):
        return None
    if not isinstance(ticket_id, int) or not (message_id is None or isinstance(message_id, int)):
        return None
    if event_type is EventType.MESSAGE_CREATED and message_id is None:
        return None
    return TicketEvent(event_type, ticket_id, message_id)
