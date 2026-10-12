"""Swagger ↔ контракт: реализованные операции совпадают с docs/openapi.yaml (ADR 0007).

Сравнивается сгенерированный FastAPI OpenAPI (/openapi.json, Swagger UI /docs) с контрактом:
путь и метод, публичность (security: []), роли x-required-roles, успешный статус,
обязательные поля запроса. Deny by default: непубличный маршрут без ролей — ошибка.
"""

import pytest
from fastapi.routing import APIRoute

from app.core.config import Settings
from app.main import API_PREFIX, create_app
from tests.api.conftest import _inline, contract, contract_operation

APP = create_app(Settings(_env_file=None, environment="test"))
GENERATED = APP.openapi()


def implemented() -> list[tuple[str, str, dict]]:
    ops = []
    for path, item in GENERATED["paths"].items():
        if not path.startswith(API_PREFIX):
            continue
        for method, op in item.items():
            ops.append((path.removeprefix(API_PREFIX), method, op))
    return ops


IDS = [op["operationId"] for _, _, op in implemented()]


@pytest.mark.parametrize("tag", ["Auth", "Vehicle", "Aggregates", "Tickets", "Uploads"])
def test_service_fully_implemented(tag):
    tagged = {
        op["operationId"]
        for item in contract()["paths"].values()
        for op in item.values()
        if isinstance(op, dict) and tag in op.get("tags", [])
    }
    assert tagged, f"В контракте нет операций с тегом {tag}"
    assert tagged <= set(IDS), f"Не реализованы: {sorted(tagged - set(IDS))}"


def test_current_user_implemented():
    assert "getCurrentUser" in IDS


@pytest.mark.parametrize(("path", "method", "op"), implemented(), ids=IDS)
def test_operation_matches_contract(path, method, op):
    c_path, c_method, c_op = contract_operation(op["operationId"])
    assert (path, method) == (c_path, c_method)

    contract_public = c_op.get("security") == []
    generated_public = not op.get("security")
    assert generated_public == contract_public, "расходится публичность операции"
    assert op.get("x-required-roles") == (
        None if contract_public else sorted(c_op["x-required-roles"])
    )

    success = {s for s in op["responses"] if s.startswith("2")}
    c_success = {s for s in c_op["responses"] if s.startswith("2")}
    assert success == c_success

    c_body = c_op.get("requestBody")
    if c_body is None:
        assert "requestBody" not in op
    else:
        c_schema = _inline(c_body)["content"]["application/json"]["schema"]
        ref = op["requestBody"]["content"]["application/json"]["schema"]["$ref"]
        g_schema = GENERATED["components"]["schemas"][ref.rsplit("/", 1)[1]]
        assert set(g_schema.get("required", [])) == set(c_schema.get("required", []))
        assert set(g_schema["properties"]) == set(c_schema["properties"])


def test_deny_by_default():
    """Каждый маршрут /v1 либо публичен в контракте, либо закрыт ролями."""
    for route in APP.routes:
        if not isinstance(route, APIRoute) or not route.path.startswith(API_PREFIX):
            continue
        _, _, c_op = contract_operation(route.operation_id)
        if c_op.get("security") == []:
            continue
        roles = (route.openapi_extra or {}).get("x-required-roles")
        dep_roles = [
            getattr(d.call, "required_roles", None)
            for d in route.dependant.dependencies
            if getattr(d.call, "required_roles", None)
        ]
        assert roles and dep_roles == [roles], f"{route.path}: нет проверки ролей"


def test_bearer_scheme_declared():
    schemes = GENERATED["components"]["securitySchemes"]
    assert any(s.get("scheme") == "bearer" for s in schemes.values())
