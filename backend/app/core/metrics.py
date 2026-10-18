"""Метрики Prometheus (глава 26, ADR 0030 п. 13).

API: запросы и их длительность по шаблону маршрута — тому же, что пишет журнал доступа
(`AccessLogMiddleware`): значения параметров пути и строка запроса в метки не попадают. Процессов
uvicorn несколько (`WEB_CONCURRENCY`), поэтому при `PROMETHEUS_MULTIPROC_DIR` счётчики пишутся в
файлы каталога, а `/metrics` собирает все процессы; каталог очищает `app.preflight` до старта
uvicorn. Только счётчики и гистограммы с метками: значения gauge умерших процессов multiprocess
не убирает, а метрика без меток создала бы файл уже при импорте. Worker'ы — `app.workers.metrics`.
"""

import os
import shutil
from pathlib import Path

from prometheus_client import (
    CONTENT_TYPE_LATEST,
    REGISTRY,
    CollectorRegistry,
    Counter,
    Histogram,
    generate_latest,
    multiprocess,
)

MULTIPROC_ENV = "PROMETHEUS_MULTIPROC_DIR"

# Нормативы ADR 0028: чтение p95 ≤ 300 мс, изменение ≤ 500 мс, p99 ≤ 1–1,5 с, тайм-аут 10 с.
DURATION_BUCKETS = (0.005, 0.01, 0.025, 0.05, 0.1, 0.2, 0.3, 0.5, 0.75, 1.0, 1.5, 2.5, 5.0, 10.0)

HTTP_REQUESTS = Counter(
    "ev_http_requests_total",
    "HTTP-запросы API по методу, шаблону маршрута и статусу",
    ["method", "route", "status"],
)
HTTP_DURATION = Histogram(
    "ev_http_request_duration_seconds",
    "Длительность HTTP-запросов API по методу и шаблону маршрута",
    ["method", "route"],
    buckets=DURATION_BUCKETS,
)


def observe_request(method: str, route: str, status: int, seconds: float) -> None:
    HTTP_REQUESTS.labels(method, route, str(status)).inc()
    HTTP_DURATION.labels(method, route).observe(seconds)


def render() -> tuple[bytes, str]:
    """Текст для `/metrics`: при multiprocess — сумма по всем процессам uvicorn."""
    if os.environ.get(MULTIPROC_ENV):
        registry = CollectorRegistry()
        multiprocess.MultiProcessCollector(registry)
        return generate_latest(registry), CONTENT_TYPE_LATEST
    return generate_latest(REGISTRY), CONTENT_TYPE_LATEST


def reset_multiproc_dir() -> None:
    """Файлы прошлого запуска контейнера дали бы счётчики умерших процессов (вызывает preflight)."""
    directory = os.environ.get(MULTIPROC_ENV)
    if not directory:
        return
    path = Path(directory)
    if path.exists():
        shutil.rmtree(path)
    path.mkdir(parents=True, exist_ok=True)
