"""Метрики worker'ов (глава 26, ADR 0030 п. 13): свой HTTP-порт (`METRICS_PORT`), один процесс.

Время последнего успешного цикла — алерт «worker молчит» (три интервала без успеха); ошибки циклов;
показатели очередей, которые видит только worker: push, анонимизация, свежесть витрины, аудит
целостности.
"""

import time

from prometheus_client import Counter, Gauge, start_http_server

WORKER_LAST_SUCCESS = Gauge(
    "ev_worker_last_success_timestamp_seconds",
    "Время (Unix) последнего успешного цикла worker'а",
    ["worker"],
)
WORKER_ERRORS = Counter(
    "ev_worker_cycle_errors_total", "Циклы worker'а, завершившиеся ошибкой", ["worker"]
)
PUSH_QUEUE_PENDING = Gauge("ev_push_queue_pending", "Доставки push в очереди (ещё не отправлены)")
PUSH_QUEUE_OLDEST_AGE = Gauge(
    "ev_push_queue_oldest_age_seconds", "Возраст самой старой неотправленной доставки push"
)
PRIVACY_QUEUE_SIZE = Gauge("ev_privacy_queue_size", "Клиенты в очереди анонимизации")
PRIVACY_QUEUE_OLDEST_AGE = Gauge(
    "ev_privacy_queue_oldest_age_seconds",
    "Сколько ждёт анонимизации клиент, дольше всех стоящий в очереди (срок 99-З — 15 дней)",
)
ANALYTICS_DATA_AGE = Gauge(
    "ev_analytics_data_age_seconds", "Возраст данных витрины аналитики (с последнего обновления)"
)
INTEGRITY_VIOLATIONS = Gauge(
    "ev_integrity_violations",
    "Нарушения целостности данных по последнему аудиту (app.tools.integrity)",
)
INTEGRITY_LAST_RUN = Gauge(
    "ev_integrity_last_run_timestamp_seconds", "Время (Unix) последнего аудита целостности"
)


class WorkerMetrics:
    """Метрики одного worker'а; `serve` поднимает HTTP-порт, если он задан."""

    def __init__(self, worker: str) -> None:
        self.worker = worker
        # Метки создаются сразу: ряд есть в /metrics до первого цикла (алерт «нет данных»).
        self._last_success = WORKER_LAST_SUCCESS.labels(worker)
        self._errors = WORKER_ERRORS.labels(worker)

    def serve(self, port: int | None) -> None:
        if port:
            start_http_server(port)

    def success(self) -> None:
        self._last_success.set(time.time())

    def error(self) -> None:
        self._errors.inc()
