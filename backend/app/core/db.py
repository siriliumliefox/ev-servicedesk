"""Сессия SQLAlchemy для запросов API. Схема — только через Alembic (Глава 2)."""

from collections.abc import Iterator
from functools import lru_cache

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings


@lru_cache
def get_engine() -> Engine:
    # hide_parameters: телефоны и прочие ПД не попадают в текст исключений и логи (ADR 0005).
    return create_engine(get_settings().database_url, pool_pre_ping=True, hide_parameters=True)


@lru_cache
def _session_factory() -> sessionmaker[Session]:
    return sessionmaker(bind=get_engine(), expire_on_commit=False)


def get_db() -> Iterator[Session]:
    """Зависимость FastAPI: сессия на запрос; в тестах подменяется."""
    with _session_factory()() as session:
        yield session
