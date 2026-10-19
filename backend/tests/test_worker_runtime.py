"""Общая основа backend (#73, D6, D12): реестр advisory-блокировок, остановка, is_active."""

import threading
import time

from sqlalchemy import select
from sqlalchemy.dialects import postgresql

from app.core.locks import AdvisoryLock
from app.models import Vehicle
from app.workers.runtime import StoppableWorker


def test_advisory_lock_keys_are_unique_and_documented() -> None:
    assert len({int(lock) for lock in AdvisoryLock}) == len(AdvisoryLock)
    assert AdvisoryLock.MAINTENANCE_REMINDERS == 15_0019  # прежние ключи — без смены при выкладке
    assert AdvisoryLock.ANALYTICS_REFRESH == 16_0020


def test_stop_interrupts_wait_at_once() -> None:
    """Остановка — Event: пауза цикла прерывается сразу, а не по окончании интервала опроса."""
    worker = StoppableWorker()
    assert worker.stopping is False
    threading.Timer(0.05, worker.stop).start()
    started = time.monotonic()
    worker._stopping.wait(10)
    assert worker.stopping is True
    assert time.monotonic() - started < 2


def test_vehicle_is_active_in_python_and_sql() -> None:
    """#73 (D6): одно правило «не удалено» — у объекта и в запросе."""
    assert Vehicle(deleted_at=None).is_active is True
    sql = str(
        select(Vehicle.id)
        .where(Vehicle.owned_active(7))
        .compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True})
    )
    assert "vehicle.user_id = 7 AND vehicle.deleted_at IS NULL" in sql
