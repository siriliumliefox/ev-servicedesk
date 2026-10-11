"""Тесты схемы на реальном PostgreSQL 16 (Глава 2). Фикстуры БД — в tests/conftest.py."""

from collections.abc import Iterator

import pytest
from sqlalchemy import Connection, Engine

from tests.conftest import BACKEND, alembic_config  # noqa: F401 — используются тестами схемы


@pytest.fixture
def conn(migrated_engine: Engine) -> Iterator[Connection]:
    """Соединение в транзакции, которая откатывается после теста."""
    with migrated_engine.connect() as connection:
        tx = connection.begin()
        yield connection
        tx.rollback()
