"""Worker уведомлений: очередь push, напоминания о ТО, push по тикетам (ADR 0019 п. 2, 7, 13).

Запуск: `python -m app.workers.notifications` (сервис `notifications-worker` в docker compose,
тот же образ, что у API). Один цикл:

1. раз в сутки, начиная с `MAINTENANCE_REMINDER_HOUR` по Europe/Minsk, — напоминания о ТО
   (повтор безопасен: задача идемпотентна и под advisory lock);
2. отправка очереди пачками, пока есть готовые строки;
3. ожидание сигнала Redis — публикация (`notifications:outbox`) или событие тикета — не
   дольше `NOTIFICATIONS_POLL_SECONDS` (повторы с паузой и потерянные сигналы).

Без Redis worker продолжает работать опросом очереди; push по тикетам в это время теряются
(как события WebSocket, at-most-once, ADR 0017 п. 9).
"""

import logging
import signal
import time
from collections.abc import Callable
from datetime import date, datetime, timedelta
from types import FrameType

from redis import Redis
from redis.client import PubSub
from redis.exceptions import RedisError

from app.core.config import Settings, get_settings
from app.core.db import SessionScope, get_session_scope
from app.core.time import BUSINESS_TZ
from app.domain.notifications.dispatch import drain
from app.domain.notifications.outbox import Outbox, outbox_channel
from app.domain.notifications.push import PushSender, get_push_sender
from app.domain.notifications.reminders import run_maintenance_reminders
from app.domain.notifications.ticket_push import TicketPush
from app.domain.tickets import events as ticket_events

logger = logging.getLogger("app.workers.notifications")

REDIS_RETRY_SECONDS = 5.0
# После сбоя задачи напоминаний — повтор не раньше чем через этот срок, а не на каждом цикле.
REMINDERS_RETRY_AFTER = timedelta(minutes=15)


class NotificationsWorker:
    def __init__(
        self,
        settings: Settings,
        scope: SessionScope,
        redis: Redis,
        sender: PushSender,
        now: Callable[[], datetime] = lambda: datetime.now(BUSINESS_TZ),
    ) -> None:
        self.settings = settings
        self.scope = scope
        self.redis = redis
        self.sender = sender
        self.now = now
        self.outbox = Outbox(redis, settings.redis_channel_prefix)
        self.ticket_push = TicketPush(redis, settings.redis_channel_prefix, sender)
        self.reminders_done_on: date | None = None
        self.reminders_retry_at: datetime | None = None
        self.stopping = False
        self._pubsub: PubSub | None = None

    # --- шаги цикла (тесты вызывают их напрямую) ---

    def reminders_due(self) -> bool:
        now = self.now()
        if self.reminders_retry_at is not None and now < self.reminders_retry_at:
            return False
        return now.hour >= self.settings.maintenance_reminder_hour and (
            self.reminders_done_on != now.date()
        )

    def run_reminders(self) -> None:
        now = self.now()
        today = now.date()
        # Сбой (БД недоступна) — повтор через REMINDERS_RETRY_AFTER; исключение уходит в цикл.
        self.reminders_retry_at = now + REMINDERS_RETRY_AFTER
        with self.scope() as db:
            created = run_maintenance_reminders(db, self.outbox, today)
        self.reminders_retry_at = None
        # None — задачу выполняет другая реплика: сегодня её больше не запускаем и здесь.
        self.reminders_done_on = today
        if created is None:
            logger.info("Напоминания о ТО выполняет другой экземпляр")

    def dispatch(self) -> int:
        with self.scope() as db:
            return drain(db, self.sender, self.settings, lambda: self.stopping)

    def handle_message(self, channel: str, data: str) -> None:
        """Сообщение pub/sub: сигнал очереди — отправка; событие тикета — push клиенту."""
        if channel == outbox_channel(self.settings.redis_channel_prefix):
            self.dispatch()
            return
        event = ticket_events.parse(data)
        if event is None:
            return
        with self.scope() as db:
            self.ticket_push.handle(db, event)

    def tick(self) -> None:
        if self.reminders_due():
            self.run_reminders()
        self.dispatch()

    # --- цикл процесса ---

    def _subscribe(self) -> PubSub | None:
        prefix = self.settings.redis_channel_prefix
        try:
            pubsub = self.redis.pubsub(ignore_subscribe_messages=True)
            pubsub.subscribe(outbox_channel(prefix))
            pubsub.psubscribe(f"{prefix}:ticket:*")
            return pubsub
        except RedisError as exc:
            logger.warning("Подписка Redis не установлена: %s", type(exc).__name__)
            return None

    def _wait(self) -> None:
        """Ждёт сигнал не дольше интервала опроса; без подписки — просто пауза."""
        deadline = time.monotonic() + self.settings.notifications_poll_seconds
        while not self.stopping and (left := deadline - time.monotonic()) > 0:
            if self._pubsub is None:
                self._pubsub = self._subscribe()
                if self._pubsub is None:
                    time.sleep(min(left, REDIS_RETRY_SECONDS))
                    continue
            try:
                message = self._pubsub.get_message(timeout=left)
            except RedisError as exc:
                logger.warning("Связь с Redis потеряна: %s", type(exc).__name__)
                self._close_pubsub()
                continue
            if message is not None:
                try:
                    self.handle_message(str(message["channel"]), str(message["data"]))
                except Exception:  # noqa: BLE001 — сбой обработки сигнала не останавливает процесс
                    logger.exception("Ошибка обработки сигнала Redis")
                return

    def _close_pubsub(self) -> None:
        if self._pubsub is not None:
            try:
                self._pubsub.close()
            except RedisError:
                pass
            self._pubsub = None

    def run_forever(self) -> None:
        logger.info(
            "Worker уведомлений запущен: push=%s, опрос %s с",
            self.settings.push_provider,
            self.settings.notifications_poll_seconds,
        )
        while not self.stopping:
            try:
                self.tick()
            except Exception:  # noqa: BLE001 — сбой цикла не останавливает процесс
                logger.exception("Ошибка цикла worker уведомлений")
            self._wait()
        self._close_pubsub()
        logger.info("Worker уведомлений остановлен")

    def stop(self, *_: object) -> None:
        self.stopping = True


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    settings = get_settings()
    worker = NotificationsWorker(
        settings,
        get_session_scope(),
        Redis.from_url(settings.redis_url, decode_responses=True),
        get_push_sender(settings),
    )

    def _stop(signum: int, frame: FrameType | None) -> None:
        worker.stop()

    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)
    worker.run_forever()


if __name__ == "__main__":
    main()
