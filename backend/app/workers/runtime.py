"""Общее у фоновых процессов (#73, D12): остановка по SIGTERM/SIGINT и запуск цикла.

Остановка — `threading.Event`, а не флаг: паузы цикла (`wait`) прерываются сразу, процесс не ждёт
конца интервала опроса.
"""

import signal
import threading
from types import FrameType
from typing import Protocol

from app.workers.metrics import WorkerMetrics


class StoppableWorker:
    """Основа worker'а: `stop` — из обработчика сигнала, `stopping` — проверка в цикле."""

    def __init__(self) -> None:
        self._stopping = threading.Event()

    @property
    def stopping(self) -> bool:
        return self._stopping.is_set()

    def stop(self, *_: object) -> None:
        self._stopping.set()


class _Runnable(Protocol):
    metrics: WorkerMetrics

    def stop(self, *_: object) -> None: ...

    def run_forever(self) -> None: ...


def run(worker: _Runnable, metrics_port: int | None) -> None:
    """Сигналы остановки → метрики на `metrics_port` (ADR 0030) → цикл до остановки."""

    def _stop(signum: int, frame: FrameType | None) -> None:
        worker.stop()

    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)
    worker.metrics.serve(metrics_port)
    worker.run_forever()
