"""Контракт docs/openapi.yaml ↔ RBAC_MATRIX.md ↔ ORM (Глава 3, Issue #18; ADR 0007).

Проверки не требуют БД: структура операций, единые ответы ошибок, пагинация коллекций,
роли ⊆ RBAC-матрицы и её полное покрытие, snake_case, поля и ENUM ↔ ORM, maxLength ≤ VARCHAR(n).
"""

import re
from functools import cache
from pathlib import Path

import pytest
import yaml
from sqlalchemy import String

from app.models import Base
from app.models.enums import (
    AttachmentType,
    KbArticleType,
    NotificationType,
    TicketCategory,
    TicketStatus,
    UserRole,
)

DOCS = Path(__file__).resolve().parents[3] / "docs"
METHODS = {"get", "post", "put", "patch", "delete"}
ROLES = {r.value for r in UserRole}
SNAKE = re.compile(r"^[a-z][a-z0-9]*(_[a-z0-9]+)*$")


@cache
def spec() -> dict:
    return yaml.safe_load((DOCS / "openapi.yaml").read_text(encoding="utf-8"))


def operations() -> list[tuple[str, str, dict, list[dict]]]:
    """(path, method, operation, параметры пути + операции)."""
    result = []
    for path, item in spec()["paths"].items():
        for method, op in item.items():
            if method in METHODS:
                result.append(
                    (path, method, op, item.get("parameters", []) + op.get("parameters", []))
                )
    return result


def op_ids() -> list[str]:
    return [op["operationId"] for _, _, op, _ in operations()]


def resolve(node: dict) -> dict:
    while "$ref" in node:
        _, kind, name = node["$ref"].removeprefix("#/").split("/")
        node = spec()["components"][kind][name]
    return node


def is_public(op: dict) -> bool:
    return op.get("security") == []


@cache
def rbac_matrix() -> dict[str, dict[str, str]]:
    rows = {}
    for line in (DOCS / "requirements" / "RBAC_MATRIX.md").read_text(encoding="utf-8").splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) == 4 and cells[1].startswith(("Да", "Нет")):
            rows[cells[0]] = dict(zip(["client", "engineer", "admin"], cells[1:], strict=True))
    return rows


def allowed(cell: str, read: bool) -> bool:
    """«Да…» — доступ; «Нет (чтение)» / «Нет (только просмотр)» — доступ только на чтение."""
    return cell.startswith("Да") or (read and ("чтение" in cell or "просмотр" in cell))


# --- Структура операций ----------------------------------------------------------------------


def test_operation_ids_unique() -> None:
    ids = op_ids()
    assert len(ids) == len(set(ids))


@pytest.mark.parametrize(("path", "method", "op", "params"), operations(), ids=op_ids())
def test_operation_shape(path: str, method: str, op: dict, params: list[dict]) -> None:
    assert op.get("tags") and op.get("summary") and op.get("description")
    responses = op["responses"]
    assert responses.get("default") == {"$ref": "#/components/responses/ServerError"}
    assert any(code.startswith("2") for code in responses)

    if is_public(op):
        assert "x-required-roles" not in op, "публичная операция не должна требовать роль"
    else:
        roles = set(op["x-required-roles"])
        assert roles and roles <= ROLES
        assert op.get("x-rbac-action"), "нужна ссылка на строку RBAC_MATRIX.md"
        assert "401" in responses
        if roles != ROLES:
            assert "403" in responses
    if "{" in path:
        assert "404" in responses
    if "requestBody" in op or any(resolve(p)["in"] == "query" for p in params):
        assert "422" in responses


@pytest.mark.parametrize(("path", "method", "op", "params"), operations(), ids=op_ids())
def test_errors_use_error_schema(path: str, method: str, op: dict, params: list[dict]) -> None:
    for code, response in op["responses"].items():
        if code == "default" or int(code) >= 400:
            schema = resolve(response)["content"]["application/json"]["schema"]
            assert schema == {"$ref": "#/components/schemas/Error"}, code


@pytest.mark.parametrize(("path", "method", "op", "params"), operations(), ids=op_ids())
def test_collections_are_paginated(path: str, method: str, op: dict, params: list[dict]) -> None:
    for code, response in op["responses"].items():
        if not code.startswith("2"):
            continue
        content = resolve(response).get("content", {}).get("application/json")
        if not content:
            continue
        schema = content["schema"]
        assert resolve(schema).get("type") != "array", "коллекция — объект {items, meta}"
        name = schema.get("$ref", "").rsplit("/", 1)[-1]
        if name.endswith("List"):
            body = spec()["components"]["schemas"][name]
            assert body["required"] == ["items", "meta"]
            assert body["properties"]["meta"] == {"$ref": "#/components/schemas/PaginationMeta"}
            refs = {p.get("$ref", "") for p in params}
            assert {
                "#/components/parameters/PageParam",
                "#/components/parameters/PageSizeParam",
            } <= refs


def test_names_are_snake_case() -> None:
    bad = [
        f"{name}.{prop}"
        for name, schema in spec()["components"]["schemas"].items()
        for part in [schema, *schema.get("allOf", [])]
        for prop in part.get("properties", {})
        if not SNAKE.match(prop)
    ]
    bad += [
        f"{op['operationId']}?{resolve(p)['name']}"
        for _, _, op, params in operations()
        for p in params
        if resolve(p)["in"] == "query" and not SNAKE.match(resolve(p)["name"])
    ]
    assert not bad


# --- RBAC ------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("path", "method", "op", "params"),
    [o for o in operations() if not is_public(o[2])],
    ids=[o[2]["operationId"] for o in operations() if not is_public(o[2])],
)
def test_roles_within_rbac_matrix(path: str, method: str, op: dict, params: list[dict]) -> None:
    matrix = rbac_matrix()
    actions = op["x-rbac-action"]
    unknown = [a for a in actions if a not in matrix]
    assert not unknown, f"нет в RBAC_MATRIX.md: {unknown}"
    read = method == "get"
    permitted = {r for r in ROLES for a in actions if allowed(matrix[a][r], read)}
    excess = set(op["x-required-roles"]) - permitted
    assert not excess, f"роли {sorted(excess)} не разрешены матрицей для {actions}"


def test_rbac_matrix_fully_covered() -> None:
    """Каждое «Да» матрицы достижимо хотя бы одной операцией."""
    reachable = {
        (action, role)
        for _, _, op, _ in operations()
        if not is_public(op)
        for action in op["x-rbac-action"]
        for role in op["x-required-roles"]
    }
    missing = [
        (action, role)
        for action, cells in rbac_matrix().items()
        for role, cell in cells.items()
        if cell.startswith("Да") and (action, role) not in reachable
    ]
    # Вход выполняется публичными операциями (security: []), роли там не объявляются.
    missing = [m for m in missing if m[0] != "Регистрация/авторизация (свой аккаунт)"]
    assert not missing


# --- OpenAPI ↔ ORM ---------------------------------------------------------------------------

# схема → (таблица, вычисляемые/вложенные поля, которых нет в таблице)
SCHEMA_TABLE = {
    "UserPublic": ("app_user", set()),
    "StaffUserCreateRequest": ("app_user", {"password"}),
    "VehicleModel": ("vehicle_model", set()),
    "Vehicle": ("vehicle", {"is_active", "vehicle_model", "current_firmware_version"}),
    "VehicleCreateRequest": ("vehicle", set()),
    "MileageCorrectionRequest": (
        "vehicle_mileage_correction",
        {"expected_current_mileage", "mileage"},
    ),
    "MaintenanceRecord": ("maintenance_record", {"aggregate_type_code", "performed_by"}),
    "MaintenanceRecordCreateRequest": ("maintenance_record", {"aggregate_type_code"}),
    "AggregateType": ("aggregate_type", set()),
    "AggregateTypeCreateRequest": ("aggregate_type", set()),
    "MaintenanceRegulation": ("maintenance_regulation", {"aggregate_type_code"}),
    "MaintenanceRegulationCreateRequest": ("maintenance_regulation", {"aggregate_type_code"}),
    "AggregateStatus": (
        "vehicle_aggregate_status",
        {
            "aggregate_type_code",
            "aggregate_type_name",
            "status",
            "percentage",
            "remaining_km",
            "remaining_days",
        },
    ),
    "AggregateStatusThresholds": ("aggregate_status_thresholds", set()),
    "AggregateStatusThresholdsUpdateRequest": ("aggregate_status_thresholds", set()),
    "Ticket": ("ticket", {"is_overdue"}),
    "TicketCreateRequest": ("ticket", {"attachments"}),
    "TicketMessage": ("ticket_message", {"author", "attachments"}),
    "TicketMessageCreateRequest": ("ticket_message", {"attachments"}),
    "KnowledgeArticle": ("knowledge_article", set()),
    "KnowledgeArticleCreateRequest": ("knowledge_article", set()),
    "KnowledgeArticleUpdateRequest": ("knowledge_article", set()),
    "DecisionTreeNodeCreateRequest": ("decision_tree_node", set()),
    "DecisionTreeNode": ("decision_tree_node", set()),
    "Notification": ("notification", set()),
    "NotificationCreateRequest": ("notification", set()),
    "FirmwareRelease": ("firmware_release", set()),
    "FirmwareReleaseCreateRequest": ("firmware_release", set()),
}


def properties(name: str) -> dict[str, dict]:
    schema = spec()["components"]["schemas"][name]
    props: dict[str, dict] = {}
    for part in [schema, *schema.get("allOf", [])]:
        part = resolve(part)
        props |= part.get("properties", {})
    return props


@pytest.mark.parametrize("name", sorted(SCHEMA_TABLE))
def test_schema_fields_exist_in_orm(name: str) -> None:
    table, computed = SCHEMA_TABLE[name]
    columns = Base.metadata.tables[table].c
    unknown = set(properties(name)) - set(columns.keys()) - computed
    assert not unknown, f"{name}: нет колонок {sorted(unknown)} в {table}"


@pytest.mark.parametrize("name", sorted(SCHEMA_TABLE))
def test_string_max_length_fits_column(name: str) -> None:
    table, _ = SCHEMA_TABLE[name]
    columns = Base.metadata.tables[table].c
    for prop, schema in properties(name).items():
        schema = resolve(schema) if "$ref" in schema else schema
        if prop not in columns or not isinstance(columns[prop].type, String):
            continue
        length = columns[prop].type.length
        if length is None or schema.get("enum"):
            continue
        if name.endswith("Request"):
            assert schema.get("maxLength"), f"{name}.{prop}: нужен maxLength ≤ {length}"
        if "maxLength" in schema:
            assert schema["maxLength"] <= length, f"{name}.{prop}: maxLength > VARCHAR({length})"


ENUMS = {
    ("UserPublic", "role"): UserRole,
    ("Ticket", "category"): TicketCategory,
    ("Ticket", "status"): TicketStatus,
    ("TicketCreateRequest", "category"): TicketCategory,
    ("TicketStatusUpdateRequest", "status"): TicketStatus,
    ("TicketCategoryCount", "category"): TicketCategory,
    ("TicketAttachmentInput", "file_type"): AttachmentType,
    ("PresignRequest", "file_type"): AttachmentType,
    ("KnowledgeArticle", "article_type"): KbArticleType,
    ("KnowledgeArticleCreateRequest", "article_type"): KbArticleType,
    ("Notification", "type"): NotificationType,
    ("NotificationCreateRequest", "type"): NotificationType,
}


@pytest.mark.parametrize(
    ("name", "prop"), sorted(ENUMS), ids=[f"{n}.{p}" for n, p in sorted(ENUMS)]
)
def test_enum_values_match_orm(name: str, prop: str) -> None:
    assert properties(name)[prop]["enum"] == [v.value for v in ENUMS[(name, prop)]]


def test_query_enums_match_orm() -> None:
    expected = {
        ("listTickets", "status"): TicketStatus,
        ("listTickets", "category"): TicketCategory,
        ("listKnowledgeArticles", "article_type"): KbArticleType,
        ("listUsers", "role"): UserRole,
        ("getTicketResolutionStats", "category"): TicketCategory,
    }
    found = {
        (op["operationId"], p["name"]): p["schema"]["enum"]
        for _, _, op, params in operations()
        for p in map(resolve, params)
        if "enum" in p.get("schema", {})
    }
    for key, enum_cls in expected.items():
        assert found[key] == [v.value for v in enum_cls], key
