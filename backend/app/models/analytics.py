"""Analytics: учёт обновлений витрины аналитики (Глава 16, ADR 0020).

Сама витрина — materialized view (миграция 0013) без ORM-моделей: запросы к ней строит
`app.domain.analytics.views`.
"""

from datetime import datetime

from sqlalchemy import DateTime, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class AnalyticsRefresh(Base):
    """Время последнего обновления витрины (ADR 0020 п. 3) — строка на materialized view.

    `refreshed_at` — момент, по состоянию на который витрина отражает данные (`computed_at`).
    """

    __tablename__ = "analytics_refresh"

    view_name: Mapped[str] = mapped_column(String(63), primary_key=True)
    refreshed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
