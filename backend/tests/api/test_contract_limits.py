"""Лимиты длины, которые сервер держит, а схема v1 не объявляет (#74, C15, ADR 0035).

Схема контракта v1 заморожена (ADR 0007): новый `maxLength` в запросе oasdiff считает ломающим.
Лимит поэтому записан в описании поля, а тест сверяет обе стороны: число из описания — граница
сервера (на границе — не ошибка длины, за ней — 422 по этому полю).
"""

from collections.abc import Callable
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

from app.models.enums import UserRole
from tests.api.conftest import API, Headers, add_vehicle
from tests.support.contract import contract

SPEC = contract()
SCHEMAS = SPEC["components"]["schemas"]


def param(path: str, name: str, method: str | None = None) -> dict:
    item = SPEC["paths"][path]
    params = item.get("parameters", []) + (item[method].get("parameters", []) if method else [])
    return next(p for p in params if p.get("name") == name)


def described(node: dict, text: str) -> None:
    assert text in " ".join(node["description"].split()), node["description"]


@pytest.fixture
def owner(as_client) -> Headers:
    return as_client("+375293300301")


@pytest.fixture
def admin(as_staff) -> Headers:
    return as_staff("+375293300302", UserRole.ADMIN)[0]


def assert_length_error(r: httpx.Response, field: str) -> None:
    assert r.status_code == 422, r.text
    body = r.json()["error"]
    assert body["code"] == "VALIDATION_ERROR"
    assert field in {e["loc"][-1] for e in body["details"]["fields"]}


def assert_no_length_error(r: httpx.Response, field: str) -> None:
    if r.status_code == 422:
        fields = r.json()["error"]["details"]["fields"]
        assert field not in {e["loc"][-1] for e in fields}, r.text


Request = Callable[[TestClient, int], httpx.Response]


def limits(owner: Headers, admin: Headers, vehicle_id: int) -> list[tuple[str, int, Request]]:
    """(поле, граница, запрос со значением этой длины)."""
    replace = f"{API}/vehicles/{vehicle_id}/aggregate-statuses"
    body: dict[str, Any] = {"replaced_at": "2026-10-01", "mileage_at_replacement": 0}
    return [
        (
            "search",
            100,
            lambda c, n: c.get(f"{API}/vehicle-models", params={"search": "я" * n}, headers=owner),
        ),
        (
            "file_name",
            255,
            lambda c, n: c.post(
                f"{API}/uploads/presign",
                json={"file_name": "ф" * (n - 4) + ".jpg", "file_type": "photo"},
                headers=owner,
            ),
        ),
        (
            "aggregateTypeCode",
            50,
            lambda c, n: c.post(f"{replace}/{'a' * n}/replace", json=body, headers=admin),
        ),
        (
            "password",
            256,
            lambda c, n: c.post(
                f"{API}/auth/staff/login", json={"phone": "+375293300303", "password": "п" * n}
            ),
        ),
        (
            "token",
            1024,
            lambda c, n: c.post(f"{API}/push-tokens", json={"token": "t" * n}, headers=owner),
        ),
        (
            "description",
            255,
            lambda c, n: c.post(
                f"{replace}/engine_oil/replace", json=body | {"description": "д" * n}, headers=admin
            ),
        ),
    ]


def test_limits_are_described_in_contract():
    described(param("/vehicle-models", "search", "get"), "до 100 символов, длиннее — 422")
    described(SCHEMAS["PresignRequest"]["properties"]["file_name"], "От 1 до 255 символов")
    replace = "/vehicles/{vehicleId}/aggregate-statuses/{aggregateTypeCode}/replace"
    described(param(replace, "aggregateTypeCode"), "до 50 символов, длиннее — 422")
    described(SCHEMAS["StaffLoginRequest"]["properties"]["password"], "До 256 символов")
    described(SCHEMAS["PushTokenRegisterRequest"]["properties"]["token"], "до 1024 символов")
    described(SCHEMAS["AggregateReplaceRequest"]["properties"]["description"], "до 255 символов")


def test_server_enforces_described_limits(client: TestClient, owner, admin):
    vehicle_id = add_vehicle(client, owner)["id"]
    for field, limit, request in limits(owner, admin, vehicle_id):
        assert_no_length_error(request(client, limit), field)
        assert_length_error(request(client, limit + 1), field)


def test_empty_file_name_is_rejected(client: TestClient, owner):
    r = client.post(
        f"{API}/uploads/presign", json={"file_name": "", "file_type": "photo"}, headers=owner
    )
    assert_length_error(r, "file_name")
