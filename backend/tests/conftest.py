"""Общие фикстуры: реальный PostgreSQL 16 (Глава 2) и Redis (Глава 10).

URL: TEST_DATABASE_URL или DATABASE_URL с суффиксом `_test` у имени БД. Тесты делают
`alembic downgrade base`, поэтому работают ТОЛЬКО с БД, чьё имя оканчивается на `_test`.
Без доступной БД тесты пропускаются; в CI REQUIRE_DB=1 превращает пропуск в ошибку.
"""

import os
from collections.abc import Iterator
from pathlib import Path

import pytest
from redis import Redis
from redis.exceptions import ConnectionError as RedisConnectionError
from sqlalchemy import Engine, create_engine
from sqlalchemy.engine import URL, make_url
from sqlalchemy.exc import OperationalError
from sqlalchemy.pool import NullPool

from alembic import command
from alembic.config import Config
from app.core.config import settings

BACKEND = Path(__file__).resolve().parents[1]


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


# Переменные, которые могли бы переключить тесты на реальный SMS-провайдер или чужие
# секреты (экспорт в оболочке разработчика). .env тесты не читают: Settings(_env_file=None).
_ISOLATED_ENV_PREFIXES = (
    "SMS_",
    "JWT_",
    "ACCESS_TOKEN_",
    "REFRESH_TOKEN_",
    "VERIFY_",
    "STAFF_LOGIN_",
)


def pytest_configure(config: pytest.Config) -> None:
    """До импорта тестовых модулей: настройки уровня модуля не видят экспорт оболочки."""
    for name in list(os.environ):
        if name.upper().startswith(_ISOLATED_ENV_PREFIXES):
            del os.environ[name]


@pytest.fixture(autouse=True)
def _isolate_auth_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """И переменные, выставленные уже во время прогона."""
    for name in list(os.environ):
        if name.upper().startswith(_ISOLATED_ENV_PREFIXES):
            monkeypatch.delenv(name, raising=False)


def _test_redis_url() -> str:
    return os.environ.get("TEST_REDIS_URL", "redis://localhost:6379/15")


@pytest.fixture(scope="session")
def redis_session() -> Iterator[Redis]:
    url = _test_redis_url()
    if url.rstrip("/").endswith("/0"):
        pytest.fail("TEST_REDIS_URL не должен указывать на БД 0 (dev): тесты очищают БД")
    client = Redis.from_url(url, decode_responses=True)
    try:
        client.ping()
    except RedisConnectionError as exc:
        if os.environ.get("REQUIRE_REDIS") == "1":
            pytest.fail(f"Redis недоступен при REQUIRE_REDIS=1: {type(exc).__name__}")
        pytest.skip(f"Redis недоступен: {type(exc).__name__}")
    yield client
    client.close()


@pytest.fixture
def real_redis(redis_session: Redis) -> Iterator[Redis]:
    redis_session.flushdb()
    yield redis_session
    redis_session.flushdb()
