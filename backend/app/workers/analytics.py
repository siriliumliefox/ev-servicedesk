"""Worker аналитики: обновление витрины фактов (ADR 0020 п. 2).

Запуск: `python -m app.workers.analytics` (сервис `analytics-worker` в docker compose, тот же
образ, что у API) — обновляет витрину сразу и затем раз в `ANALYTICS_REFRESH_SECONDS`.
`--once` — одно обновление и выход (smoke образа, тесты, ручной пересчёт).
Отдельный процесс, а не шаг `notifications-worker`: пересчёт не задерживает push.
Раз в сутки — аудит целостности `app.tools.integrity` для мониторинга (глава 26, ADR 0030 п. 13).
"""

import argparse
import logging
import sys
import time
from datetime import UTC, datetime

from sqlalchemy import func, select

from app.core.config import Settings, get_settings
from app.core.db import SessionScope, get_session_scope
from app.core.logging import configure_logging
from app.domain.analytics.refresh import refresh_views
from app.models import AnalyticsRefresh
from app.tools.integrity import run_checks
from app.workers import metrics, runtime
from app.workers.runtime import StoppableWorker

logger = logging.getLogger("app.workers.analytics")

INTEGRITY_EVERY_SECONDS = 24 * 3600


class AnalyticsWorker(StoppableWorker):
    def __init__(self, settings: Settings, scope: SessionScope) -> None:
        super().__init__()
        self.settings = settings
        self.scope = scope
        self.metrics = metrics.WorkerMetrics("analytics")
        self._integrity_at: float | None = None

    def refresh(self) -> bool:
        """Одно обновление; False — витрину сейчас обновляет другой экземпляр."""
        with self.scope() as db:
            done = refresh_views(db)
        if done:
            logger.info("Витрина аналитики обновлена")
        else:
            logger.info("Витрину аналитики обновляет другой экземпляр")
        return done

    def observe(self) -> None:
        """Возраст витрины — по самому давнему обновлению её частей."""
        with self.scope() as db:
            refreshed = db.scalar(select(func.min(AnalyticsRefresh.refreshed_at)))
        if refreshed is not None:
            age = (datetime.now(UTC) - refreshed).total_seconds()
            metrics.ANALYTICS_DATA_AGE.set(max(age, 0.0))

    def check_integrity(self) -> int | None:
        """Аудит целостности — не чаще раза в сутки; None — ещё не пора."""
        now = time.monotonic()
        if self._integrity_at is not None and now - self._integrity_at < INTEGRITY_EVERY_SECONDS:
            return None
        with self.scope() as db:
            violations = run_checks(db)
        self._integrity_at = now
        total = sum(v.count for v in violations)
        metrics.INTEGRITY_VIOLATIONS.set(total)
        metrics.INTEGRITY_LAST_RUN.set(time.time())
        for v in violations:
            logger.error("Нарушение целостности %s: %d", v.check.name, v.count)
        return total

    def cycle(self) -> None:
        self.refresh()
        self.observe()
        self.check_integrity()

    def run_forever(self) -> None:
        logger.info(
            "Worker аналитики запущен: обновление раз в %s с",
            self.settings.analytics_refresh_seconds,
        )
        while not self._stopping.is_set():
            try:
                self.cycle()
                self.metrics.success()
            except Exception:  # noqa: BLE001 — сбой обновления не останавливает процесс
                self.metrics.error()
                logger.exception("Ошибка обновления витрины аналитики")
            self._stopping.wait(self.settings.analytics_refresh_seconds)
        logger.info("Worker аналитики остановлен")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Обновление витрины аналитики (ADR 0020)")
    parser.add_argument("--once", action="store_true", help="одно обновление и выход")
    args = parser.parse_args(argv)
    settings = get_settings()
    configure_logging(log_format=settings.log_format)
    worker = AnalyticsWorker(settings, get_session_scope())
    if args.once:
        return 0 if worker.refresh() else 1

    runtime.run(worker, settings.metrics_port)
    return 0


if __name__ == "__main__":
    sys.exit(main())
