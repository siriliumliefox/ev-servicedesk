"""Advisory-блокировки PostgreSQL (#73, D12): реестр ключей фоновых задач-одиночек.

Ключ — номер главы и ADR (`15_0019` — глава 15, ADR 0019), чтобы новые задачи не заняли чужой.
Блокировка транзакционная: снимается вместе с commit или rollback, повиснуть после сбоя не может.
"""

from enum import IntEnum, unique

from sqlalchemy import text
from sqlalchemy.orm import Session


@unique
class AdvisoryLock(IntEnum):
    MAINTENANCE_REMINDERS = 15_0019  # суточные напоминания о ТО (глава 15, ADR 0019)
    ANALYTICS_REFRESH = 16_0020  # пересчёт витрины аналитики (глава 16, ADR 0020)


def try_xact_lock(db: Session, lock: AdvisoryLock) -> bool:
    """`pg_try_advisory_xact_lock`: True — блокировка взята до конца транзакции, False — занята."""
    return bool(
        db.execute(text("SELECT pg_try_advisory_xact_lock(:k)"), {"k": int(lock)}).scalar_one()
    )
