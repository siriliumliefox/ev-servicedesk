"""Worker ПД: анонимизация после отзыва согласия и сроки хранения (ADR 0029 пп. 18–19).

Запуск: `python -m app.workers.privacy` (сервис `privacy-worker` в docker compose, тот же образ,
что у API): проход сразу и затем раз в `PRIVACY_RUN_SECONDS` (час). `--once` — один проход.

Проход: каждому клиенту очереди — SMS «данные удалены» до обнуления телефона (best effort,
не повторяется: отметка в Redis; тестовым номерам не отправляется), затем анонимизация. Не
дошло SMS — клиент ждёт следующего прохода, пока до срока больше суток; потом анонимизация
без уведомления (ERROR в лог). Раз в сутки — удаление по срокам хранения. В лог — только id.
"""

import argparse
import logging
import signal
import sys
import threading
from collections.abc import Callable
from datetime import UTC, datetime
from types import FrameType

from redis import Redis

from app.core.config import Settings, get_settings
from app.core.db import SessionScope, get_session_scope
from app.core.logging import configure_logging
from app.core.redis import get_redis
from app.core.storage import ObjectStorage, get_storage
from app.domain.auth.sms import SmsError, SmsProvider, get_sms_provider_for
from app.domain.users import privacy

logger = logging.getLogger("app.workers.privacy")

SMS_TEXT = "EV-ServiceDesk: ваши персональные данные удалены по вашему запросу."
NOTIFIED_PREFIX = "privacy:notified:"
DAY = 24 * 3600


class PrivacyWorker:
    def __init__(
        self,
        settings: Settings,
        scope: SessionScope,
        redis: Redis,
        sms: SmsProvider,
        storage: ObjectStorage,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self.settings = settings
        self.scope = scope
        self.redis = redis
        self.sms = sms
        self.storage = storage
        self.now = now
        self._purged_at: datetime | None = None
        self._stopping = threading.Event()

    def _notified(self, item: privacy.Due, late: bool) -> bool:
        """SMS до обнуления телефона; True — можно анонимизировать."""
        if item.phone is None or item.phone in self.settings.test_phones:
            return True
        key = f"{NOTIFIED_PREFIX}{item.user_id}"
        if self.redis.exists(key):
            return True
        try:
            self.sms.send(item.phone, SMS_TEXT)
        except SmsError:
            if not late:
                logger.warning("Клиент #%d: SMS об удалении не отправлено — повтор", item.user_id)
                return False
            logger.error("Клиент #%d: SMS об удалении не отправлено, срок истекает", item.user_id)
            return True
        self.redis.set(key, 1, ex=int(privacy.DEADLINE.total_seconds()) + DAY)
        return True

    def anonymize_due(self) -> int:
        now = self.now()
        with self.scope() as db:
            queue = privacy.due(db)
        done = 0
        for item in queue:
            late = now - item.withdrawn_at >= privacy.LATE
            if late:
                logger.error("Клиент #%d в очереди анонимизации больше 14 дней", item.user_id)
            if not self._notified(item, late):
                continue
            with self.scope() as db:
                if privacy.anonymize(db, self.storage, item.user_id, now):
                    done += 1
                    logger.info("Клиент #%d анонимизирован", item.user_id)
        return done

    def purge(self) -> privacy.Purged | None:
        """Сроки хранения — не чаще раза в сутки."""
        now = self.now()
        if self._purged_at is not None and (now - self._purged_at).total_seconds() < DAY:
            return None
        with self.scope() as db:
            purged = privacy.purge_expired(db, now)
        self._purged_at = now
        logger.info(
            "Сроки хранения: refresh %d, push %d, доставок %d",
            purged.refresh_tokens,
            purged.push_tokens,
            purged.deliveries,
        )
        return purged

    def run_once(self) -> None:
        self.anonymize_due()
        self.purge()

    def run_forever(self) -> None:
        logger.info("Worker ПД запущен: проход раз в %s с", self.settings.privacy_run_seconds)
        while not self._stopping.is_set():
            try:
                self.run_once()
            except Exception:  # noqa: BLE001 — сбой прохода не останавливает процесс
                logger.exception("Ошибка прохода worker ПД")
            self._stopping.wait(self.settings.privacy_run_seconds)
        logger.info("Worker ПД остановлен")

    def stop(self, *_: object) -> None:
        self._stopping.set()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Анонимизация ПД и сроки хранения (ADR 0029)")
    parser.add_argument("--once", action="store_true", help="один проход и выход")
    args = parser.parse_args(argv)
    configure_logging()
    settings = get_settings()
    worker = PrivacyWorker(
        settings,
        get_session_scope(),
        get_redis(),
        get_sms_provider_for(settings),
        get_storage(),
    )
    if args.once:
        worker.run_once()
        return 0

    def _stop(signum: int, frame: FrameType | None) -> None:
        worker.stop()

    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)
    worker.run_forever()
    return 0


if __name__ == "__main__":
    sys.exit(main())
