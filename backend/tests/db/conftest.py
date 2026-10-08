"""Тесты схемы на реальном PostgreSQL 16 (Глава 2).

URL: TEST_DATABASE_URL или DATABASE_URL с суффиксом `_test` у имени БД. Тесты делают
`alembic downgrade base`, поэтому работают ТОЛЬКО с БД, чьё имя оканчивается на `_test`.
Без доступной БД тесты пропускаются; в CI REQUIRE_DB=1 превращает пропуск в ошибку.
"""

import os
from collections.abc import Iterator
from pathlib import Path

import pytest
from sqlalchemy import Connection, Engine, create_engine
from sqlalchemy.engine import URL, make_url
from sqlalchemy.exc import OperationalError
from sqlalchemy.pool import NullPool

from alembic import command
from alembic.config import Config
from app.core.config import settings

BACKEND = Path(__file__).resolve().parents[2]


def _test_url() -> URL:
    raw = os.environ.get("TEST_DATABASE_URL")
    if raw:
        return make_url(raw)
    base = make_url(settings.database_url)
    return base.set(database=f"{base.database}_test")


def alembic_config(url: URL) -> Config:
    cfg = Config(str(BACKEND / "alembic.ini"))
    cfg.attributes["database_url"] = url.render_as_string(hide_password=False)
    cfg.attributes["configure_logger"] = False
    return cfg


@pytest.fixture(scope="session")
def db_url() -> URL:
    url = _test_url()
    if not (url.database or "").endswith("_test"):
        pytest.fail("Имя тестовой БД должно оканчиваться на _test (защита от downgrade dev-БД)")
    engine = create_engine(url, poolclass=NullPool)
    try:
        with engine.connect():
            pass
    except OperationalError as exc:
        if os.environ.get("REQUIRE_DB") == "1":
            pytest.fail(f"PostgreSQL недоступен при REQUIRE_DB=1: {type(exc.orig).__name__}")
        pytest.skip(f"PostgreSQL недоступен: {type(exc.orig).__name__}")
    finally:
        engine.dispose()
    return url


@pytest.fixture(scope="session")
def migrated_engine(db_url: URL) -> Iterator[Engine]:
    cfg = alembic_config(db_url)
    command.downgrade(cfg, "base")
    command.upgrade(cfg, "head")
    engine = create_engine(db_url, poolclass=NullPool)
    yield engine
    engine.dispose()


@pytest.fixture
def conn(migrated_engine: Engine) -> Iterator[Connection]:
    """Соединение в транзакции, которая откатывается после теста."""
    with migrated_engine.connect() as connection:
        tx = connection.begin()
        yield connection
        tx.rollback()
