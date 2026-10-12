"""Сессия SQLAlchemy для запросов API. Схема — только через Alembic (Глава 2)."""

from collections.abc import Callable, Iterator
from contextlib import AbstractContextManager
from functools import lru_cache
from typing import Any

from sqlalchemy import Engine, create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings

BIGINT_MAX = 2**63 - 1  # id таблиц (ADR 0003): больше — ошибка драйвера и 500, а не 404/422


def is_db_id(value: int) -> bool:
    """Значение в диапазоне id таблиц: вне его строки нет, а запрос — ошибка драйвера и 500."""
    return 1 <= value <= BIGINT_MAX


def escape_like(value: str) -> str:
    """Литерал для `LIKE ... ESCAPE '\\'`: `%`, `_` и `\\` из ввода — обычные символы."""
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def get_by_id[M](db: Session, model: type[M], value: int, **kwargs: Any) -> M | None:
    """`Session.get`, но id вне диапазона BIGINT — None (строки нет), а не ошибка драйвера."""
    return db.get(model, value, **kwargs) if is_db_id(value) else None


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


# Фабрика коротких сессий: `with scope() as db: ...`.
SessionScope = Callable[[], AbstractContextManager[Session]]


def get_session_scope() -> SessionScope:
    """Зависимость долгоживущих подключений (WebSocket, ADR 0017 п. 9): сессия — на каждое
    обращение к БД, а не на всё подключение, чтобы оно не держало соединение пула.
    В тестах подменяется.
    """
    return _session_factory()


def constraint_name(exc: IntegrityError) -> str | None:
    """Имя нарушенного ограничения PostgreSQL — чтобы перевести гонку в ответ контракта."""
    return getattr(getattr(exc.orig, "diag", None), "constraint_name", None)
