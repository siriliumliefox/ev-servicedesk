"""Сигнал worker'у «в очереди push появились строки» (ADR 0019 п. 2).

Канал Redis pub/sub `{prefix}:notifications:outbox`, публикуется после COMMIT. Сигнал —
только ускорение: потерянный сигнал worker подхватит опросом очереди.
"""

import logging
from dataclasses import dataclass

from redis import Redis
from redis.exceptions import RedisError

logger = logging.getLogger(__name__)


def outbox_channel(prefix: str) -> str:
    return f"{prefix}:notifications:outbox"


@dataclass(frozen=True)
class Outbox:
    redis: Redis | None
    prefix: str

    @property
    def channel(self) -> str:
        return outbox_channel(self.prefix)

    def wake(self) -> None:
        if self.redis is None:
            return
        try:
            self.redis.publish(self.channel, "1")
        except RedisError as exc:
            logger.warning("Сигнал очереди push не отправлен: %s", type(exc).__name__)
