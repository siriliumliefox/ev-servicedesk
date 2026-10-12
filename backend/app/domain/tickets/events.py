"""События тикета в Redis pub/sub, канал `{prefix}:ticket:{id}` (ADR 0017 п. 9, docs/asyncapi.yaml).

Публикуются после COMMIT и содержат только идентификаторы: `{"type", "ticket_id",
"message_id"?}`. Данные события каждое WebSocket-подключение читает из БД и формирует для
своего получателя по правилам REST (ПД сотрудника скрыты от клиента, presigned GET для
вложений) — так ПД не попадают в Redis, а доступ проверяется заново на каждом событии.
Те же события может слушать push (глава 15) без изменений Tickets. Доставка at-most-once:
сбой публикации не отменяет записанное — клиент догружает через `after_id`.

Каналы pub/sub общие для всего сервера Redis (номер БД не учитывается), поэтому имя канала
начинается с `redis_channel_prefix` из настроек приложения (по умолчанию — окружение):
стенды и параллельные прогоны тестов на одном Redis не получают чужих событий.
"""

import logging
from dataclasses import dataclass
from typing import Annotated, Literal

from pydantic import BaseModel, Field, StrictInt, TypeAdapter, ValidationError
from redis import Redis
from redis.exceptions import RedisError

logger = logging.getLogger(__name__)


class MessageCreated(BaseModel, frozen=True):
    type: Literal["message.created"] = "message.created"
    ticket_id: StrictInt
    message_id: StrictInt


class TicketUpdated(BaseModel, frozen=True):
    type: Literal["ticket.updated"] = "ticket.updated"
    ticket_id: StrictInt


TicketEvent = Annotated[MessageCreated | TicketUpdated, Field(discriminator="type")]
_EVENT: TypeAdapter[TicketEvent] = TypeAdapter(TicketEvent)


@dataclass(frozen=True)
class TicketEvents:
    """Публикация событий тикетов; Redis и префикс каналов — из зависимостей приложения."""

    redis: Redis
    prefix: str

    def channel(self, ticket_id: int) -> str:
        return f"{self.prefix}:ticket:{ticket_id}"

    def message_created(self, ticket_id: int, message_id: int) -> None:
        self._publish(MessageCreated(ticket_id=ticket_id, message_id=message_id))

    def ticket_updated(self, ticket_id: int) -> None:
        self._publish(TicketUpdated(ticket_id=ticket_id))

    def _publish(self, event: MessageCreated | TicketUpdated) -> None:
        try:
            self.redis.publish(self.channel(event.ticket_id), event.model_dump_json())
        except RedisError as exc:
            logger.warning("Событие тикета не опубликовано: %s", type(exc).__name__)


def parse(raw: str | bytes) -> MessageCreated | TicketUpdated | None:
    """Событие из канала; чужой или повреждённый формат — None (пропускается)."""
    try:
        return _EVENT.validate_json(raw)
    except ValidationError:
        return None
