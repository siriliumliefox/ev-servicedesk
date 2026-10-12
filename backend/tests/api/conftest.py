"""Интеграционные фикстуры API: реальные PostgreSQL и Redis, фейковый SMS-провайдер.

Каждый тест — во внешней транзакции, которая откатывается; commit сервисов становится
SAVEPOINT (join_transaction_mode="create_savepoint").
"""

import re
import threading
import uuid
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from functools import cache
from pathlib import Path
from typing import Any

import httpx
import pytest
import yaml
from fastapi import FastAPI
from fastapi.testclient import TestClient
from openapi_schema_validator import OAS30Validator
from redis import Redis
from sqlalchemy import Engine
from sqlalchemy.orm import Session

from app.api.deps import get_sms_provider
from app.core.config import Settings, get_settings
from app.core.db import get_db, get_session_scope
from app.core.redis import PubSubHub, get_pubsub_hub, get_redis
from app.core.security import hash_password
from app.core.storage import FakeObjectStorage, ObjectStorage, get_storage
from app.domain.auth.sms import FakeSmsProvider
from app.main import create_app
from app.models import AppUser, PdConsent, Ticket
from app.models.enums import TicketCategory, TicketStatus, UserRole
from tests.conftest import _test_redis_url

DOCS = Path(__file__).resolve().parents[3] / "docs"
API = "/v1"
POLICY = "2026-10"
STAFF_PASSWORD = "Staff-pass-123"
# Каналы pub/sub не зависят от номера БД Redis: параллельные прогоны на одном сервере
# разделяются префиксом каналов, своим у каждого прогона.
RUN_CHANNEL_PREFIX = f"test-{uuid.uuid4().hex[:12]}"


def api_settings(**overrides: Any) -> Settings:
    """Настройки тестов: без .env разработчика и всегда с фейковым SMS-провайдером."""
    values: dict[str, Any] = {
        "environment": "test",
        "jwt_secret": "api-test-secret-" + "q" * 32,
        "sms_code_secret": "api-test-sms-secret-" + "w" * 32,
        "sms_provider": "fake",
        "redis_channel_prefix": RUN_CHANNEL_PREFIX,
    }
    return Settings(_env_file=None, **(values | overrides))


@pytest.fixture(autouse=True)
def _run_channel_prefix(monkeypatch: pytest.MonkeyPatch) -> None:
    """Каналы событий тикетов (events.channel) — с префиксом прогона."""
    monkeypatch.setattr(get_settings(), "redis_channel_prefix", RUN_CHANNEL_PREFIX)


@pytest.fixture
def settings() -> Settings:
    return api_settings()


@pytest.fixture
def db(migrated_engine: Engine) -> Iterator[Session]:
    with migrated_engine.connect() as connection:
        tx = connection.begin()
        session = Session(
            bind=connection, join_transaction_mode="create_savepoint", expire_on_commit=False
        )
        yield session
        session.close()
        tx.rollback()


@pytest.fixture
def sms() -> FakeSmsProvider:
    return FakeSmsProvider()


@pytest.fixture
def storage(fake_storage: FakeObjectStorage) -> ObjectStorage:
    """Хранилище вложений API-тестов: в памяти; тест с MinIO подменяет фикстуру на s3_storage."""
    return fake_storage


def pubsub_hub(settings: Settings) -> PubSubHub:
    """Общая подписка WebSocket — на тестовом Redis (как в app.main, но с TEST_REDIS_URL)."""
    return PubSubHub.from_settings(settings, url=_test_redis_url())


@pytest.fixture
def app(
    settings: Settings,
    db: Session,
    real_redis: Redis,
    sms: FakeSmsProvider,
    storage: ObjectStorage,
) -> FastAPI:
    application = create_app(settings)
    # Одна сессия теста на одном соединении: запросы REST и обработчики WebSocket (у каждого
    # подключения — свой поток) обращаются к ней по очереди. В приложении у каждого запроса
    # и каждого обращения WebSocket — своя сессия.
    lock = threading.Lock()

    def shared_db() -> Iterator[Session]:
        with lock:
            yield db

    @contextmanager
    def session_scope() -> Iterator[Session]:
        with lock:
            yield db

    application.dependency_overrides[get_settings] = lambda: settings
    application.dependency_overrides[get_db] = shared_db
    application.dependency_overrides[get_session_scope] = lambda: session_scope
    application.dependency_overrides[get_redis] = lambda: real_redis
    hub = pubsub_hub(settings)
    application.dependency_overrides[get_pubsub_hub] = lambda: hub
    application.dependency_overrides[get_sms_provider] = lambda: sms
    application.dependency_overrides[get_storage] = lambda: storage
    return application


@pytest.fixture
def client(app: FastAPI) -> TestClient:
    return TestClient(app)


def code_from(sms: FakeSmsProvider, phone: str) -> str:
    match = re.search(r"\b(\d{4,8})\b", sms.last_text(phone) or "")
    assert match, f"SMS на {phone} не отправлено"
    return match.group(1)


@pytest.fixture
def login_client(client: TestClient, sms: FakeSmsProvider) -> Callable[[str], dict]:
    """Полный вход клиента по SMS; возвращает тело ответа verify-code."""

    def _login(phone: str, policy: str | None = POLICY) -> dict:
        r = client.post(f"{API}/auth/phone/request-code", json={"phone": phone})
        assert r.status_code == 200, r.text
        body: dict[str, Any] = {"phone": phone, "code": code_from(sms, phone)}
        if policy:
            body["pd_policy_version"] = policy
        r = client.post(f"{API}/auth/phone/verify-code", json=body)
        assert r.status_code == 200, r.text
        return r.json()

    return _login


@pytest.fixture
def make_staff(db: Session) -> Callable[..., AppUser]:
    def _make(phone: str, role: UserRole = UserRole.ENGINEER, active: bool = True) -> AppUser:
        user = AppUser(
            phone=phone, role=role, password_hash=hash_password(STAFF_PASSWORD), is_active=active
        )
        db.add(user)
        db.commit()
        return user

    return _make


@pytest.fixture
def make_client_user(db: Session) -> Callable[..., AppUser]:
    def _make(phone: str, consent: bool = True, active: bool = True) -> AppUser:
        user = AppUser(phone=phone, role=UserRole.CLIENT, is_active=active)
        db.add(user)
        db.flush()
        if consent:
            db.add(PdConsent(user_id=user.id, policy_version=POLICY))
        db.commit()
        return user

    return _make


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


# ---------- Сверка ответов с docs/openapi.yaml ----------


@cache
def contract() -> dict:
    return yaml.safe_load((DOCS / "openapi.yaml").read_text(encoding="utf-8"))


def _inline(node: Any) -> Any:
    """Разворачивает $ref в самостоятельную JSON-схему для OAS30Validator."""
    if isinstance(node, dict):
        if "$ref" in node:
            _, kind, group, name = node["$ref"].split("/")
            return _inline(contract()[kind][group][name])
        return {k: _inline(v) for k, v in node.items()}
    if isinstance(node, list):
        return [_inline(v) for v in node]
    return node


def contract_operation(operation_id: str) -> tuple[str, str, dict]:
    for path, item in contract()["paths"].items():
        for method, op in item.items():
            if isinstance(op, dict) and op.get("operationId") == operation_id:
                return path, method, op
    raise KeyError(operation_id)


def assert_contract(response: httpx.Response, operation_id: str) -> None:
    """Статус объявлен в контракте, тело валидно по его схеме."""
    _, _, op = contract_operation(operation_id)
    status = str(response.status_code)
    assert status in op["responses"] or (
        response.status_code >= 500 and "default" in op["responses"]
    ), f"{operation_id}: статус {status} не объявлен в контракте"
    declared = _inline(op["responses"].get(status) or op["responses"]["default"])
    schema = declared.get("content", {}).get("application/json", {}).get("schema")
    if schema is None:
        assert not response.content, f"{operation_id} {status}: тело не ожидается"
        return
    OAS30Validator(schema).validate(response.json())


# ---------- Авто, персонал и тикеты (Главы 11–12) ----------

ZEEKR_VIN = "L6TZ0010000000001"  # распознаёт мок-декодер
UNKNOWN_VIN = "LSVAU2183R2100001"  # мок не знает — модель вручную

Headers = dict[str, str]


@pytest.fixture
def as_client(login_client: Callable[[str], dict]) -> Callable[[str], Headers]:
    def _as(phone: str) -> Headers:
        return bearer(login_client(phone)["access_token"])

    return _as


@pytest.fixture
def as_staff(client: TestClient, make_staff) -> Callable[..., tuple[Headers, AppUser]]:
    def _as(phone: str, role: UserRole = UserRole.ENGINEER) -> tuple[Headers, AppUser]:
        user = make_staff(phone, role)
        r = client.post(
            f"{API}/auth/staff/login", json={"phone": phone, "password": STAFF_PASSWORD}
        )
        assert r.status_code == 200, r.text
        return bearer(r.json()["access_token"]), user

    return _as


@pytest.fixture
def make_ticket(db: Session) -> Callable[..., Ticket]:
    def _make(
        vehicle_id: int,
        engineer: AppUser | None = None,
        status: TicketStatus = TicketStatus.IN_PROGRESS,
    ) -> Ticket:
        if engineer is None and status is TicketStatus.IN_PROGRESS:
            status = TicketStatus.NEW
        now = datetime.now(UTC)
        ticket = Ticket(
            vehicle_id=vehicle_id,
            category=TicketCategory.MAINTENANCE,
            status=status,
            description="Плановое ТО",
            assigned_engineer_id=engineer.id if engineer else None,
            sla_due_at=now + timedelta(hours=4),
            resolved_at=now if status is TicketStatus.RESOLVED else None,
        )
        db.add(ticket)
        db.commit()
        return ticket

    return _make


def model_id(client: TestClient, headers: Headers, search: str) -> int:
    r = client.get(f"{API}/vehicle-models", params={"search": search}, headers=headers)
    assert_contract(r, "searchVehicleModels")
    return r.json()["items"][0]["id"]


def add_vehicle(client: TestClient, headers: Headers, vin: str = ZEEKR_VIN, **extra) -> dict:
    r = client.post(f"{API}/vehicles", json={"vin": vin, **extra}, headers=headers)
    assert r.status_code == 201, r.text
    assert_contract(r, "createVehicle")
    return r.json()
