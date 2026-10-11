"""Общие фикстуры: реальный PostgreSQL 16 (Глава 2), Redis (Глава 10) и S3/MinIO (Глава 13).

URL: TEST_DATABASE_URL или DATABASE_URL с суффиксом `_test` у имени БД. Тесты делают
`alembic downgrade base`, поэтому работают ТОЛЬКО с БД, чьё имя оканчивается на `_test`.
Без доступной БД тесты пропускаются; в CI REQUIRE_DB=1 превращает пропуск в ошибку.
То же для Redis (REQUIRE_REDIS=1) и S3 (REQUIRE_S3=1).
"""

import os
from collections.abc import Iterator
from pathlib import Path

import boto3
import pytest
from botocore.client import BaseClient
from botocore.config import Config as BotoConfig
from botocore.exceptions import BotoCoreError, ClientError
from redis import Redis
from redis.exceptions import ConnectionError as RedisConnectionError
from sqlalchemy import Engine, create_engine
from sqlalchemy.engine import URL, make_url
from sqlalchemy.exc import OperationalError
from sqlalchemy.pool import NullPool

from alembic import command
from alembic.config import Config
from app.core.config import DEFAULT_S3_ACCESS_KEY, DEFAULT_S3_SECRET_KEY, settings
from app.core.storage import FakeObjectStorage, S3ObjectStorage

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
        pytest.fail("Имя тестовой БД должно оканчиваться на _test (защита от downgrade dev-БД)")
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


# --- S3 (Глава 13, ADR 0017 п. 11): MinIO из docker compose или контейнер backend-ci ---------


def _test_s3_config() -> dict[str, str]:
    """TEST_S3_* или настройки приложения (.env) с бакетом `<S3_BUCKET>-test`.

    Пустые ключи — как в docker-compose.yml (`${S3_ACCESS_KEY:-...}`): заглушки local.
    """
    env = os.environ.get
    return {
        "endpoint": env("TEST_S3_ENDPOINT") or settings.s3_endpoint,
        "bucket": env("TEST_S3_BUCKET") or f"{settings.s3_bucket}-test",
        "access_key": env("TEST_S3_ACCESS_KEY") or settings.s3_access_key or DEFAULT_S3_ACCESS_KEY,
        "secret_key": env("TEST_S3_SECRET_KEY") or settings.s3_secret_key or DEFAULT_S3_SECRET_KEY,
        "region": env("TEST_S3_REGION") or settings.s3_region,
    }


def _s3_admin(config: dict[str, str]) -> BaseClient:
    """Клиент для подготовки бакета (создание, очистка) — вне интерфейса ObjectStorage."""
    return boto3.client(
        "s3",
        endpoint_url=config["endpoint"],
        aws_access_key_id=config["access_key"],
        aws_secret_access_key=config["secret_key"],
        region_name=config["region"],
        config=BotoConfig(
            s3={"addressing_style": "path"}, connect_timeout=3, retries={"max_attempts": 1}
        ),
    )


def _empty_bucket(client: BaseClient, bucket: str) -> None:
    for page in client.get_paginator("list_objects_v2").paginate(Bucket=bucket):
        keys = [{"Key": obj["Key"]} for obj in page.get("Contents", [])]
        if keys:
            client.delete_objects(Bucket=bucket, Delete={"Objects": keys, "Quiet": True})


@pytest.fixture(scope="session")
def s3_config() -> dict[str, str]:
    """Параметры тестового S3 — ключевые аргументы S3ObjectStorage(**s3_config)."""
    config = _test_s3_config()
    if not config["bucket"].endswith("-test"):
        pytest.fail("Имя тестового бакета должно оканчиваться на -test: тесты очищают бакет")
    return config


@pytest.fixture(scope="session")
def s3_session(s3_config: dict[str, str]) -> Iterator[S3ObjectStorage]:
    """Тестовый бакет (создаётся при отсутствии); без S3 — skip, при REQUIRE_S3=1 — ошибка."""
    client = _s3_admin(s3_config)
    try:
        try:
            client.head_bucket(Bucket=s3_config["bucket"])
        except ClientError as exc:
            if exc.response.get("ResponseMetadata", {}).get("HTTPStatusCode") != 404:
                raise
            client.create_bucket(Bucket=s3_config["bucket"])
    except (BotoCoreError, ClientError) as exc:
        if os.environ.get("REQUIRE_S3") == "1":
            pytest.fail(f"S3 недоступен при REQUIRE_S3=1: {type(exc).__name__}")
        pytest.skip(f"S3 недоступен: {type(exc).__name__}")
    finally:
        client.close()
    yield S3ObjectStorage(**s3_config)


@pytest.fixture
def s3_storage(s3_session: S3ObjectStorage, s3_config: dict[str, str]) -> Iterator[S3ObjectStorage]:
    """Хранилище на реальном S3 API с пустым тестовым бакетом до и после теста."""
    client = _s3_admin(s3_config)
    _empty_bucket(client, s3_config["bucket"])
    yield s3_session
    _empty_bucket(client, s3_config["bucket"])
    client.close()


@pytest.fixture
def fake_storage() -> FakeObjectStorage:
    """Хранилище в памяти — для тестов, которым не нужен настоящий S3 API."""
    return FakeObjectStorage()
