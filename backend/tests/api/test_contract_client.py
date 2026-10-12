"""Самопроверка сверки ответов с контрактом (ContractClient, ADR 0021 п. 2).

Сверщик заменяет Pact: если он молча пропускает ответы, расхождения реализации и
docs/openapi.yaml перестают ловиться во всём наборе API-тестов.
"""

import httpx
import pytest
from jsonschema.exceptions import ValidationError

from app.api.deps import get_current_user
from app.core.errors import ApiError
from tests.api.conftest import API, assert_contract, operation_for


@pytest.mark.parametrize(
    ("method", "path", "operation_id"),
    [
        ("GET", f"{API}/vehicles/5", "getVehicle"),
        ("DELETE", f"{API}/vehicles/5", "deleteVehicle"),
        ("GET", f"{API}/notifications/published", "listPublishedNotifications"),
        ("PATCH", f"{API}/users/7", "updateUser"),
        ("GET", f"{API}/me", "getCurrentUser"),
        ("GET", "/health", None),
        ("GET", f"{API}/_debug/sms/last-code", None),
        ("PUT", f"{API}/me", None),
    ],
)
def test_operation_matching(method, path, operation_id):
    assert operation_for(method, path) == operation_id


def test_undeclared_status_fails(app, client):
    """getCurrentUser не объявляет 409 — такой ответ должен уронить тест."""

    def conflict():
        raise ApiError(409, "SOME_CONFLICT", "x")

    app.dependency_overrides[get_current_user] = conflict
    with pytest.raises(AssertionError, match="не объявлен в контракте"):
        client.get(f"{API}/me")
    with client.unchecked():
        assert client.get(f"{API}/me").status_code == 409


def test_invalid_body_fails():
    """Тело не по схеме UserPublic (нет обязательных полей) — ошибка валидации схемы."""
    response = httpx.Response(200, json={"id": "not-an-int"})
    with pytest.raises(ValidationError):
        assert_contract(response, "getCurrentUser")
