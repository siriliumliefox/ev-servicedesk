"""Витрина аналитики и worker её обновления (Глава 16, ADR 0020 п. 1–3)."""

from collections.abc import Iterator
from contextlib import contextmanager

import pytest
from prometheus_client import REGISTRY
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.locks import AdvisoryLock
from app.domain.analytics.refresh import refresh_views
from app.domain.analytics.views import VIEWS
from app.workers.analytics import AnalyticsWorker


@pytest.mark.parametrize("view", VIEWS, ids=lambda v: v.name)
def test_view_columns_match_query_description(db: Session, view) -> None:
    """Описание колонок в коде совпадает с materialized view миграции."""
    columns = db.execute(
        text(
            "SELECT attname FROM pg_attribute "
            "WHERE attrelid = CAST(:name AS regclass) AND attnum > 0 AND NOT attisdropped "
            "ORDER BY attnum"
        ),
        {"name": view.name},
    ).scalars()
    assert list(columns) == [c.name for c in view.columns]


def test_second_instance_skips_refresh(migrated_engine: Engine) -> None:
    with migrated_engine.connect() as holder, migrated_engine.connect() as other:
        lock = {"k": int(AdvisoryLock.ANALYTICS_REFRESH)}
        holder.execute(text("SELECT pg_advisory_xact_lock(:k)"), lock)
        with Session(bind=other) as db:
            assert refresh_views(db) is False
        holder.rollback()


@contextmanager
def scope_of(db: Session) -> Iterator[Session]:
    yield db


def worker(db: Session, seconds: float = 10) -> AnalyticsWorker:
    settings = Settings(_env_file=None, environment="test", analytics_refresh_seconds=seconds)
    return AnalyticsWorker(settings, lambda: scope_of(db))


def test_worker_refreshes_on_start_and_stops(db: Session) -> None:
    w = worker(db)
    calls: list[bool] = []
    original = w.refresh

    def refresh_and_stop() -> bool:
        calls.append(original())
        w.stop()
        return calls[-1]

    w.refresh = refresh_and_stop  # type: ignore[method-assign]
    w.run_forever()
    assert calls == [True]


def test_worker_survives_refresh_error(db: Session, caplog: pytest.LogCaptureFixture) -> None:
    w = worker(db)
    attempts = 0

    def failing() -> bool:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise RuntimeError("БД недоступна")
        w.stop()
        return True

    w.refresh = failing  # type: ignore[method-assign]
    w._stopping.wait = lambda timeout=None: False  # type: ignore[method-assign]  # без паузы
    w.run_forever()
    assert attempts == 2
    assert "Ошибка обновления витрины аналитики" in caplog.text


def test_refresh_interval_bounds() -> None:
    with pytest.raises(ValueError):
        Settings(_env_file=None, environment="test", analytics_refresh_seconds=5)


def test_cycle_metrics_and_daily_integrity(db: Session) -> None:
    """Свежесть витрины и аудит целостности в метриках (глава 26, ADR 0030 п. 13)."""
    w = worker(db)
    w.cycle()
    assert REGISTRY.get_sample_value("ev_analytics_data_age_seconds") >= 0
    assert REGISTRY.get_sample_value("ev_integrity_violations") == 0
    assert REGISTRY.get_sample_value("ev_integrity_last_run_timestamp_seconds") > 0
    assert w.check_integrity() is None, "аудит — не чаще раза в сутки"
