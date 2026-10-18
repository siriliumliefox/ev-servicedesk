"""IDOR: подмена id авто во всех операциях `/vehicles/{vehicleId}/*` (Глава 25, ADR 0029 п. 6).

Сводная матрица object-level по образцу тикетов (`test_ticket_security.py`): участники ×
цели × операции, каждая клетка — в своём мире (транзакция теста), чтобы изменение одного
участника не влияло на ответ другому. Правило (ADR 0014, RBAC-01, ADR 0029 п. 6):
- роль вне `x-required-roles` — 403 FORBIDDEN;
- авто не видно участнику — 404 «Автомобиль не найден» (существование не раскрывается);
- удалённое авто — только чтение (изменение — 403);
- иначе операция проходит авторизацию (ответ не 401/403/404 по авто).
"""

from dataclasses import dataclass

import pytest

from app.models.enums import TicketStatus, UserRole
from tests.api.conftest import API, add_vehicle
from tests.support.contract import contract_operation

VEHICLE_NOT_FOUND = "Автомобиль не найден"

# operationId → (путь после /vehicles/{id}, тело, изменяет ли авто)
OPS = {
    "getVehicle": ("", None, False),
    "listMaintenanceRecords": ("/maintenance-records", None, False),
    "listAggregateStatuses": ("/aggregate-statuses", None, False),
    "updateVehicleMileage": ("/mileage", {"mileage": 10}, True),
    "deleteVehicle": ("", None, True),
    "correctVehicleMileage": (
        "/mileage-corrections",
        {"expected_current_mileage": 0, "mileage": 0, "reason": "Ошибка ввода"},
        True,
    ),
    "createMaintenanceRecord": (
        "/maintenance-records",
        {"performed_at": "2026-01-01", "mileage_at_service": 0},
        True,
    ),
    "replaceAggregateStatus": (
        "/aggregate-statuses/engine_oil/replace",
        {"replaced_at": "2026-01-01", "mileage_at_replacement": 0},
        True,
    ),
    "setVehicleFirmware": ("/firmware", {"firmware_release_id": 1}, True),
}

ACTORS = ("owner", "stranger", "engineer_assigned", "engineer_other", "admin")
ROLE = {
    "owner": "client",
    "stranger": "client",
    "engineer_assigned": "engineer",
    "engineer_other": "engineer",
    "admin": "admin",
}
# Кому видно авто: активное — владельцу, инженеру по тикету и админу; удалённое — без владельца.
VISIBLE = {
    "active": {"owner", "engineer_assigned", "admin"},
    "deleted": {"engineer_assigned", "admin"},
}


@dataclass
class World:
    headers: dict[str, dict[str, str]]
    vehicle_id: int


@pytest.fixture
def world_for(client, as_client, as_staff, make_ticket):
    def _build(target: str) -> World:
        owner = as_client("+375296670001")
        headers = {"owner": owner, "stranger": as_client("+375296670002")}
        headers["engineer_assigned"], engineer = as_staff("+375296670003")
        headers["engineer_other"], _ = as_staff("+375296670004")
        headers["admin"], _ = as_staff("+375296670005", UserRole.ADMIN)
        vid = add_vehicle(client, owner)["id"]
        make_ticket(vid, engineer, TicketStatus.IN_PROGRESS)
        if target == "deleted":
            assert client.delete(f"{API}/vehicles/{vid}", headers=owner).status_code == 204
        return World(headers, vid)

    return _build


def expected(op_id: str, actor: str, target: str) -> str:
    _, _, op = contract_operation(op_id)
    if ROLE[actor] not in op["x-required-roles"]:
        return "role-403"
    if actor not in VISIBLE[target]:
        return "404"
    if OPS[op_id][2] and target == "deleted":
        return "403"
    return "allowed"


CASES = [(op, actor, target) for op in OPS for actor in ACTORS for target in VISIBLE]


@pytest.mark.parametrize(("op_id", "actor", "target"), CASES, ids=["-".join(c) for c in CASES])
def test_vehicle_idor_matrix(client, world_for, op_id, actor, target):
    world = world_for(target)
    suffix, body, _ = OPS[op_id]
    _, method, _ = contract_operation(op_id)
    r = client.request(
        method,
        f"{API}/vehicles/{world.vehicle_id}{suffix}",
        json=body,
        headers=world.headers[actor],
    )
    error = r.json().get("error", {}) if r.content else {}
    want = expected(op_id, actor, target)
    if want == "role-403":
        assert (r.status_code, error.get("code")) == (403, "FORBIDDEN"), r.text
    elif want == "404":
        assert (r.status_code, error.get("message")) == (404, VEHICLE_NOT_FOUND), r.text
    elif want == "403":
        assert r.status_code == 403, r.text
    else:
        assert r.status_code not in (401, 403), r.text
        assert error.get("message") != VEHICLE_NOT_FOUND, r.text
