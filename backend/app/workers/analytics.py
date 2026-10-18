"""Worker аналитики: обновление витрины фактов (ADR 0020 п. 2).

Запуск: `python -m app.workers.analytics` (сервис `analytics-worker` в docker compose, тот же
образ, что у API) — обновляет витрину сразу и затем раз в `ANALYTICS_REFRESH_SECONDS`.
`--once` — одно обновление и выход (smoke образа, тесты, ручной пересчёт).
Отдельный процесс, а не шаг `notifications-worker`: пересчёт не задерживает push.
"""

import argparse
import logging
import signal
import sys
import threading
from types import FrameType

from app.core.config import Settings, get_settings
from app.core.db import SessionScope, get_session_scope
from app.core.logging import configure_logging
from app.domain.analytics.refresh import refresh_views

logger = logging.getLogger("app.workers.analytics")


class AnalyticsWorker:
    def __init__(self, settings: Settings, scope: SessionScope) -> None:
        self.settings = settings
        self.scope = scope
        self._stopping = threading.Event()

    def refresh(self) -> bool:
        """Одно обновление; False — витрину сейчас обновляет другой экземпляр."""
        with self.scope() as db:
            done = refresh_views(db)
        if done:
            logger.info("Витрина аналитики обновлена")
        else:
            logger.info("Витрину аналитики обновляет другой экземпляр")
        return done

    def run_forever(self) -> None:
        logger.info(
            "Worker аналитики запущен: обновление раз в %s с",
            self.settings.analytics_refresh_seconds,
        )
        while not self._stopping.is_set():
            try:
                self.refresh()
            except Exception:  # noqa: BLE001 — сбой обновления не останавливает процесс
                logger.exception("Ошибка обновления витрины аналитики")
            self._stopping.wait(self.settings.analytics_refresh_seconds)
        logger.info("Worker аналитики остановлен")

    def stop(self, *_: object) -> None:
        self._stopping.set()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Обновление витрины аналитики (ADR 0020)")
    parser.add_argument("--once", action="store_true", help="одно обновление и выход")
    args = parser.parse_args(argv)
    configure_logging()
    worker = AnalyticsWorker(get_settings(), get_session_scope())
    if args.once:
        return 0 if worker.refresh() else 1

    def _stop(signum: int, frame: FrameType | None) -> None:
        worker.stop()

    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)
    worker.run_forever()
    return 0


if __name__ == "__main__":
    sys.exit(main())
