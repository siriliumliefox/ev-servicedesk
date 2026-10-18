"""Сессия SQLAlchemy для запросов API. Схема — только через Alembic (Глава 2)."""

from collections.abc import AsyncIterator, Callable
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


def is_db_text(value: str, max_length: int) -> bool:
    """Строка помещается в столбец: длиннее или с NUL (PostgreSQL не хранит его в text, запрос с
    ним — ошибка драйвера и 500) такой строки нет."""
    return len(value) <= max_length and "\x00" not in value


def escape_like(value: str) -> str:
    """Литерал для `LIKE ... ESCAPE '\\'`: `%`, `_` и `\\` из ввода — обычные символы."""
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def get_by_id[M](db: Session, model: type[M], value: int, **kwargs: Any) -> M | None:
    """`Session.get`, но id вне диапазона BIGINT — None (строки нет), а не ошибка драйвера."""
    return db.get(model, value, **kwargs) if is_db_id(value) else None


@lru_cache
def get_engine() -> Engine:
    # hide_parameters: телефоны и прочие ПД не попадают в текст исключений и логи (ADR 0005).
    settings = get_settings()
    return create_engine(
        settings.database_url,
        pool_pre_ping=True,
        hide_parameters=True,
        pool_size=settings.db_pool_size,
        max_overflow=settings.db_max_overflow,
        pool_timeout=settings.db_pool_timeout_seconds,
    )


@lru_cache
def _session_factory() -> sessionmaker[Session]:
    return sessionmaker(bind=get_engine(), expire_on_commit=False)


async def get_db() -> AsyncIterator[Session]:
    """Зависимость FastAPI: сессия на запрос; в тестах подменяется.

    Асинхронный генератор — открытие и закрытие сессии в цикле событий, без захода в пул потоков
    (глава 24, ADR 0028 п. 18): синхронная зависимость закрывала бы сессию отдельным заходом, и
    запрос, уже отработавший, держал бы соединение, пока ждёт свободный поток. На пике все потоки
    заняты запросами, ждущими соединение, а все соединения — запросами, ждущими поток: процесс
    вставал. Сессия до первого запроса соединения не берёт; закрытие — возврат соединения в пул
    (ROLLBACK по локальной сети, доли миллисекунды).
    """
    session = _session_factory()()
    try:
        yield session
    finally:
        session.close()


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
