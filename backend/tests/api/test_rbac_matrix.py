"""Автоматизированная проверка RBAC-матрицы по каждой операции контракта (Глава 25, ADR 0029 п. 6).

Роли операции — `x-required-roles` в docs/openapi.yaml (их соответствие RBAC_MATRIX.md проверяет
tests/contract/test_openapi_contract.py). Для каждой защищённой операции и каждой роли:
- роль вне `x-required-roles` — 403 FORBIDDEN, и для существующего, и для несуществующего id
  (проверка роли идёт раньше поиска объекта: ответ не раскрывает существование);
- роль из `x-required-roles` — не 401 и не отказ по роли (object-level 403/404 допустимы: RBAC-01,
  RBAC-04, — их проверяют матрицы object-level).
Каждый ответ сверяется с контрактом (`ContractClient`): 403 должен быть объявлен.
"""

import re

import pytest

from app.models.enums import UserRole
from tests.api.conftest import API, STAFF_PASSWORD, bearer, error_code
from tests.api.test_security import BODIES
from tests.support.contract import contract

ROLE_DENIED = "Недостаточно прав"  # сообщение require_roles (app/api/deps.py)
GHOST_ID = "987654321"


def protected_operations() -> list[tuple[str, str, str, list[str]]]:
    """(operationId, метод, путь, роли) защищённых операций контракта."""
    found = []
    for path, item in contract()["paths"].items():
        for method, op in item.items():
            if isinstance(op, dict) and op.get("x-required-roles"):
                found.append((op["operationId"], method, path, op["x-required-roles"]))
    return sorted(found)


OPERATIONS = protected_operations()


def test_every_protected_operation_is_checked():
    """Полнота: обход не пропускает операции — их число растёт вместе с контрактом."""
    assert len(OPERATIONS) >= 62
    assert all(set(roles) <= {r.value for r in UserRole} for *_, roles in OPERATIONS)


@pytest.fixture
def role_headers(client, login_client, make_staff) -> dict[str, dict[str, str]]:
    headers = {"client": bearer(login_client("+375296660001")["access_token"])}
    for phone, role in (("+375296660002", UserRole.ENGINEER), ("+375296660003", UserRole.ADMIN)):
        make_staff(phone, role)
        r = client.post(
            f"{API}/auth/staff/login", json={"phone": phone, "password": STAFF_PASSWORD}
        )
        assert r.status_code == 200, r.text
        headers[role.value] = bearer(r.json()["access_token"])
    return headers


def _request(client, method: str, path: str, op_id: str, headers: dict, object_id: str):
    kwargs = {"headers": headers}
    if op_id in BODIES:
        kwargs["json"] = BODIES[op_id]
    return client.request(method, API + re.sub(r"\{\w+\}", object_id, path), **kwargs)


@pytest.mark.parametrize(
    ("op_id", "method", "path", "roles"), OPERATIONS, ids=[op[0] for op in OPERATIONS]
)
def test_role_matrix(client, role_headers, op_id, method, path, roles):
    for role, headers in role_headers.items():
        if role in roles:
            r = _request(client, method, path, op_id, headers, "1")
            assert r.status_code != 401, (op_id, role, r.text)
            if r.status_code == 403:
                assert r.json()["error"]["message"] != ROLE_DENIED, (op_id, role)
            continue
        for object_id in ("1", GHOST_ID):
            r = _request(client, method, path, op_id, headers, object_id)
            assert r.status_code == 403, (op_id, role, object_id, r.text)
            assert error_code(r) == "FORBIDDEN", (op_id, role, object_id)
