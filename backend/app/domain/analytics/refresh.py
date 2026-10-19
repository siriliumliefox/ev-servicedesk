"""Обновление витрины аналитики (ADR 0020 п. 2, 3).

Все витрины обновляются одной транзакцией под advisory lock: вторая копия worker в это время
пропускает обновление, а API видит витрину и её `computed_at` согласованными. REFRESH ...
CONCURRENTLY не блокирует чтение витрины на время пересчёта.
"""

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.locks import AdvisoryLock, try_xact_lock
from app.domain.analytics.views import VIEWS


def refresh_views(db: Session) -> bool:
    """Пересчитывает витрину и фиксирует время; False — обновляет другой экземпляр."""
    if not try_xact_lock(db, AdvisoryLock.ANALYTICS_REFRESH):
        db.rollback()
        return False
    for view in VIEWS:
        # Время до пересчёта: витрина отражает данные не раньше этого момента.
        started = db.execute(text("SELECT clock_timestamp()")).scalar_one()
        db.execute(text(f"REFRESH MATERIALIZED VIEW CONCURRENTLY {view.name}"))
        db.execute(
            text("UPDATE analytics_refresh SET refreshed_at = :at WHERE view_name = :name"),
            {"at": started, "name": view.name},
        )
    db.commit()
    return True
