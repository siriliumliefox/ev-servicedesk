"""Пул потоков и пул соединений не блокируют друг друга (глава 24, ADR 0028 п. 18).

Найдено прогоном k6 (peak): у синхронного маршрута зависимости и обработчик выполняются
отдельными заходами в пул потоков. Если запрос держит соединение между заходами, на пике все
потоки заняты запросами, ждущими соединение, а все соединения — запросами, ждущими поток, и
процесс встаёт. Здесь это воспроизводится на настоящем PostgreSQL с узкими пулами: 2 потока,
1 соединение, 12 одновременных запросов.
"""

import inspect
from collections.abc import AsyncIterator, Iterator
from concurrent.futures import ThreadPoolExecutor

import anyio.to_thread
import pytest
from fastapi.testclient import TestClient
from redis import Redis
from sqlalchemy import Engine, create_engine, delete
from sqlalchemy.engine import URL
from sqlalchemy.orm import Session, sessionmaker

from app.api.deps import get_current_user
from app.core.config import Settings, get_settings
from app.core.db import get_db
from app.core.redis import get_redis
from app.core.security import create_access_token, decode_access_token
from app.main import create_app
from app.models import AppUser
from app.models.enums import UserRole
from tests.api.conftest import API, api_settings, bearer

PHONE = "+375297240001"


@pytest.fixture
def user_id(migrated_engine: Engine) -> Iterator[int]:
    with Session(migrated_engine) as s:
        user = AppUser(phone=PHONE, role=UserRole.CLIENT)
        s.add(user)
        s.commit()
        uid = user.id
    yield uid
    with Session(migrated_engine) as s:
        s.execute(delete(AppUser).where(AppUser.id == uid))
        s.commit()


@pytest.fixture
def narrow_engine(db_url: URL) -> Iterator[Engine]:
    """Одно соединение, ожидание — 1 с (как пул на пике: всё разобрано)."""
    engine = create_engine(db_url, pool_size=1, max_overflow=0, pool_timeout=1)
    yield engine
    engine.dispose()


def test_auth_dependency_returns_connection_to_pool(
    migrated_engine: Engine, real_redis: Redis, user_id: int
) -> None:
    settings = api_settings()
    token = create_access_token(user_id, "client", settings)
    with Session(migrated_engine, expire_on_commit=False) as db:
        user = get_current_user(db, real_redis, decode_access_token(token, settings))
        assert user.id == user_id and user.phone == PHONE, "объект пользователя не сброшен"
        assert not db.in_transaction(), "соединение удерживается до следующего захода в пул потоков"


def test_db_session_closes_without_thread_hop() -> None:
    assert inspect.isasyncgenfunction(get_db), "закрытие сессии не должно ждать свободный поток"


def test_many_requests_with_narrow_pools_do_not_deadlock(
    narrow_engine: Engine, real_redis: Redis, user_id: int
) -> None:
    settings: Settings = api_settings()
    factory = sessionmaker(bind=narrow_engine, expire_on_commit=False)

    async def narrow_db() -> AsyncIterator[Session]:
        session = factory()
        try:
            yield session
        finally:
            session.close()

    app = create_app(settings)
    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_db] = narrow_db
    app.dependency_overrides[get_redis] = lambda: real_redis
    headers = bearer(create_access_token(user_id, "client", settings))
    with TestClient(app) as client:
        client.portal.call(_narrow_threads)
        with ThreadPoolExecutor(12) as pool:
            codes = list(
                pool.map(lambda _: client.get(f"{API}/me", headers=headers).status_code, range(12))
            )
    assert codes == [200] * 12, f"взаимная блокировка пулов: {codes}"


def _narrow_threads() -> None:
    anyio.to_thread.current_default_thread_limiter().total_tokens = 2
