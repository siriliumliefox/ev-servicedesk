"""Сверка ответов API с docs/openapi.yaml (ADR 0007, ADR 0021 п. 2).

Общая для pytest (`ContractClient` в tests/api/conftest.py) и сквозного сценария
(`scripts/e2e_backend.py`): статус объявлен у операции, тело валидно по её схеме.
"""

import re
from functools import cache
from pathlib import Path
from typing import Any

import httpx
import yaml
from openapi_schema_validator import OAS30Validator

DOCS = Path(__file__).resolve().parents[3] / "docs"
API = "/v1"


@cache
def contract() -> dict:
    return yaml.safe_load((DOCS / "openapi.yaml").read_text(encoding="utf-8"))


def inline_schema(node: Any) -> Any:
    """Разворачивает $ref в самостоятельную JSON-схему для OAS30Validator."""
    if isinstance(node, dict):
        if "$ref" in node:
            _, kind, group, name = node["$ref"].split("/")
            return inline_schema(contract()[kind][group][name])
        return {k: inline_schema(v) for k, v in node.items()}
    if isinstance(node, list):
        return [inline_schema(v) for v in node]
    return node


def contract_operation(operation_id: str) -> tuple[str, str, dict]:
    for path, item in contract()["paths"].items():
        for method, op in item.items():
            if isinstance(op, dict) and op.get("operationId") == operation_id:
                return path, method, op
    raise KeyError(operation_id)


@cache
def _operation_patterns() -> list[tuple[str, re.Pattern[str], str]]:
    """(метод, шаблон пути, operationId); пути без параметров — раньше шаблонных."""
    patterns = []
    for path, item in contract()["paths"].items():
        regex = re.compile(API + re.sub(r"\{[^}]+\}", "[^/]+", path) + "/?")
        for method, op in item.items():
            if isinstance(op, dict) and "operationId" in op:
                patterns.append((path.count("{"), method.upper(), regex, op["operationId"]))
    return [(m, rx, op) for _, m, rx, op in sorted(patterns, key=lambda p: p[0])]


def operation_for(method: str, path: str) -> str | None:
    """operationId контракта для запроса; None — путь вне контракта."""
    for op_method, regex, operation_id in _operation_patterns():
        if op_method == method.upper() and regex.fullmatch(path):
            return operation_id
    return None


def assert_contract(response: httpx.Response, operation_id: str) -> None:
    """Статус объявлен в контракте, тело валидно по его схеме."""
    _, _, op = contract_operation(operation_id)
    status = str(response.status_code)
    assert status in op["responses"] or (
        response.status_code >= 500 and "default" in op["responses"]
    ), f"{operation_id}: статус {status} не объявлен в контракте"
    declared = inline_schema(op["responses"].get(status) or op["responses"]["default"])
    schema = declared.get("content", {}).get("application/json", {}).get("schema")
    if schema is None:
        assert not response.content, f"{operation_id} {status}: тело не ожидается"
        return
    OAS30Validator(schema).validate(response.json())
