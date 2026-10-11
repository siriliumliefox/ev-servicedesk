"""Интеграционные фикстуры API: реальные PostgreSQL и Redis, фейковый SMS-провайдер.

Каждый тест — во внешней транзакции, которая откатывается; commit сервисов становится
SAVEPOINT (join_transaction_mode="create_savepoint").
"""

import re
from collections.abc import Callable, Iterator
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
from app.core.db import get_db
from app.core.redis import get_redis
from app.core.security import hash_password
from app.domain.auth.sms import FakeSmsProvider
from app.main import create_app
from app.models import AppUser, PdConsent
from app.models.enums import UserRole

DOCS = Path(__file__).resolve().parents[3] / "docs"
API = "/v1"
POLICY = "2026-10"
STAFF_PASSWORD = "Staff-pass-123"


def api_settings(**overrides: Any) -> Settings:
    values: dict[str, Any] = {
        "environment": "test",
        "jwt_secret": "api-test-secret-" + "q" * 32,
        "sms_code_secret": "api-test-sms-secret-" + "w" * 32,
    }
    return Settings(**(values | overrides))


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
def app(settings: Settings, db: Session, real_redis: Redis, sms: FakeSmsProvider) -> FastAPI:
    application = create_app(settings)
    application.dependency_overrides[get_settings] = lambda: settings
    application.dependency_overrides[get_db] = lambda: db
    application.dependency_overrides[get_redis] = lambda: real_redis
    application.dependency_overrides[get_sms_provider] = lambda: sms
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
