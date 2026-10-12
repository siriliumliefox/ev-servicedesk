"""Vehicle Service (Глава 11, ADR 0014): интеграция с Auth Service и сверка с контрактом.

Токены — настоящие: клиент входит по SMS-коду, персонал — по паролю (Глава 10). Тикеты
(Глава 13) создаются напрямую в БД — от них зависит доступ инженера. Каждый ответ
сверяется со схемой docs/openapi.yaml (`assert_contract`).
"""

from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy import event, func, select

from app.core.config import Settings
from app.core.time import BUSINESS_TZ
from app.domain.vehicles import access
from app.models import AggregateType, MaintenanceRecord, Vehicle
from app.models.enums import TicketStatus, UserRole
from app.models.vehicles import VehicleMileageCorrection
from tests.api.conftest import (
    API,
    UNKNOWN_VIN,
    ZEEKR_VIN,
    add_vehicle,
    bearer,
    model_id,
)

# ---------- Основной сценарий (интеграционный тест чек-листа) ----------


def test_add_list_mileage_history_flow(client, as_client, as_staff, make_ticket, db):
    owner = as_client("+375291100001")

    vehicle = add_vehicle(client, owner)
    assert vehicle["vehicle_model"] == {"brand": "Zeekr", "model": "001", "trim": None}
    assert vehicle["mileage"] == 0 and vehicle["is_active"] is True
    vid = vehicle["id"]

    r = client.get(f"{API}/vehicles", headers=owner)
    assert [v["id"] for v in r.json()["items"]] == [vid]

    r = client.patch(f"{API}/vehicles/{vid}/mileage", json={"mileage": 12000}, headers=owner)
    assert r.status_code == 200
    assert r.json()["mileage"] == 12000

    r = client.patch(f"{API}/vehicles/{vid}/mileage", json={"mileage": 11999}, headers=owner)
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "MILEAGE_DECREASE"

    engineer_headers, engineer = as_staff("+375291100002")
    ticket = make_ticket(vid, engineer)
    r = client.post(
        f"{API}/vehicles/{vid}/maintenance-records",
        json={
            "aggregate_type_code": "cabin_filter",
            "performed_at": date.today().isoformat(),
            "mileage_at_service": 15000,
            "description": "Замена салонного фильтра",
        },
        headers=engineer_headers,
    )
    assert r.status_code == 201, r.text
    assert r.json()["performed_by"]["id"] == engineer.id

    r = client.get(f"{API}/vehicles/{vid}/maintenance-records", headers=owner)
    [record] = r.json()["items"]
    assert record["aggregate_type_code"] == "cabin_filter"
    assert record["mileage_at_service"] == 15000

    r = client.get(f"{API}/vehicles/{vid}", headers=owner)
    assert r.json()["mileage"] == 15000, "пробег на момент работы выше — пробег авто поднят"
    assert db.get(MaintenanceRecord, record["id"]).ticket_id == ticket.id


def test_several_vehicles_per_account_with_pagination(client, as_client):
    owner = as_client("+375291100011")
    first = add_vehicle(client, owner)
    second = add_vehicle(
        client, owner, UNKNOWN_VIN, vehicle_model_id=model_id(client, owner, "Li Auto")
    )

    r = client.get(f"{API}/vehicles", params={"page_size": 1, "page": 2}, headers=owner)
    body = r.json()
    assert body["meta"] == {"page": 2, "page_size": 1, "total_items": 2, "total_pages": 2}
    assert [v["id"] for v in body["items"]] == [second["id"]]
    assert first["id"] != second["id"]

    r = client.get(f"{API}/vehicles", params={"page_size": 101}, headers=owner)
    assert r.status_code == 422


# ---------- VIN-декодер ----------


def test_unrecognized_vin_requires_manual_model(client, as_client):
    owner = as_client("+375291100021")
    r = client.post(f"{API}/vehicles", json={"vin": UNKNOWN_VIN}, headers=owner)
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "VIN_DECODE_FAILED"

    voyah = model_id(client, owner, "voyah free")
    vehicle = add_vehicle(client, owner, UNKNOWN_VIN, vehicle_model_id=voyah)
    assert vehicle["vehicle_model"] == {"brand": "Voyah", "model": "Free", "trim": None}

    r = client.post(
        f"{API}/vehicles",
        json={"vin": "LSVAU2183R2100002", "vehicle_model_id": 10**9},
        headers=owner,
    )
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "VEHICLE_MODEL_NOT_FOUND"


@pytest.mark.parametrize(
    "vin",
    ["L6TZ001000000000", "L6TZ00100000000O1", "l6tz0010000000001", "L6TZ001 000000001"],
)
def test_invalid_vin_is_422_without_echoing_value(client, as_client, vin):
    owner = as_client("+375291100031")
    r = client.post(f"{API}/vehicles", json={"vin": vin}, headers=owner)
    assert r.status_code == 422
    assert vin not in r.text, "VIN — ПД: значение в ответ не возвращается"


def test_model_search_escapes_wildcards(client, as_client):
    owner = as_client("+375291100041")
    r = client.get(f"{API}/vehicle-models", params={"search": "zee"}, headers=owner)
    assert [m["brand"] for m in r.json()["items"]] == ["Zeekr"]
    r = client.get(f"{API}/vehicle-models", params={"search": "%"}, headers=owner)
    assert r.json()["items"] == []
    r = client.get(f"{API}/vehicle-models", headers=owner)
    assert r.json()["meta"]["total_items"] >= 3


# ---------- Конфликт VIN (бизнес-правило, ADR 0014) ----------


def test_same_vin_on_two_accounts_is_conflict(client, as_client, db):
    first = as_client("+375291100051")
    second = as_client("+375291100052")
    vehicle = add_vehicle(client, first)

    r = client.post(f"{API}/vehicles", json={"vin": ZEEKR_VIN}, headers=second)
    assert r.status_code == 409
    error = r.json()["error"]
    assert error["code"] == "VIN_REGISTERED_TO_ANOTHER_ACCOUNT"
    assert error["details"] is None
    assert str(vehicle["id"]) not in r.text and "+375291100051" not in r.text

    r = client.post(f"{API}/vehicles", json={"vin": ZEEKR_VIN}, headers=first)
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "VIN_ALREADY_ADDED"
    assert db.scalar(select(func.count()).select_from(Vehicle).where(Vehicle.vin == ZEEKR_VIN)) == 1


def test_owner_readding_deleted_vehicle_restores_history(client, as_client, as_staff, make_ticket):
    owner = as_client("+375291100061")
    vid = add_vehicle(client, owner)["id"]
    engineer_headers, engineer = as_staff("+375291100062")
    make_ticket(vid, engineer)
    r = client.post(
        f"{API}/vehicles/{vid}/maintenance-records",
        json={"performed_at": "2026-01-10", "mileage_at_service": 500, "description": "Осмотр"},
        headers=engineer_headers,
    )
    assert r.status_code == 201

    r = client.delete(f"{API}/vehicles/{vid}", headers=owner)
    assert r.status_code == 204
    assert client.get(f"{API}/vehicles", headers=owner).json()["items"] == []

    restored = add_vehicle(client, owner)
    assert restored["id"] == vid and restored["is_active"] is True and restored["mileage"] == 500
    history = client.get(f"{API}/vehicles/{vid}/maintenance-records", headers=owner).json()
    assert len(history["items"]) == 1


def test_new_owner_after_deletion_gets_clean_record(client, as_client):
    old_owner = as_client("+375291100071")
    new_owner = as_client("+375291100072")
    old_id = add_vehicle(client, old_owner)["id"]
    client.patch(f"{API}/vehicles/{old_id}/mileage", json={"mileage": 900}, headers=old_owner)
    assert client.delete(f"{API}/vehicles/{old_id}", headers=old_owner).status_code == 204

    new = add_vehicle(client, new_owner)
    assert new["id"] != old_id and new["mileage"] == 0, "история прежнего владельца не видна"
    r = client.get(f"{API}/vehicles/{old_id}", headers=new_owner)
    assert r.status_code == 404


# ---------- Object-level доступ ----------


def test_client_sees_only_own_active_vehicles(client, as_client):
    owner = as_client("+375291100081")
    stranger = as_client("+375291100082")
    vid = add_vehicle(client, owner)["id"]

    for method, path, body in [
        ("get", f"/vehicles/{vid}", None),
        ("patch", f"/vehicles/{vid}/mileage", {"mileage": 10}),
        ("delete", f"/vehicles/{vid}", None),
        ("get", f"/vehicles/{vid}/maintenance-records", None),
    ]:
        r = client.request(method, f"{API}{path}", json=body, headers=stranger)
        assert r.status_code == 404, f"{method} {path}: чужое авто должно быть невидимо"

    assert client.delete(f"{API}/vehicles/{vid}", headers=owner).status_code == 204
    assert client.get(f"{API}/vehicles/{vid}", headers=owner).status_code == 404
    assert client.delete(f"{API}/vehicles/{vid}", headers=owner).status_code == 404


def test_engineer_access_follows_tickets(client, as_client, as_staff, make_ticket, db):
    owner = as_client("+375291100091")
    vid = add_vehicle(client, owner)["id"]
    eng_headers, engineer = as_staff("+375291100092")
    _, other_engineer = as_staff("+375291100093")
    mileage = {"mileage": 100}

    # Без тикета — авто невидимо.
    assert client.get(f"{API}/vehicles/{vid}", headers=eng_headers).status_code == 404

    # Чужой тикет в работе — тоже.
    make_ticket(vid, other_engineer)
    assert client.get(f"{API}/vehicles/{vid}", headers=eng_headers).status_code == 404

    # Очередь (неназначенный new): просмотр — да, изменение — 403.
    queue = make_ticket(vid)
    assert client.get(f"{API}/vehicles/{vid}", headers=eng_headers).status_code == 200
    r = client.patch(f"{API}/vehicles/{vid}/mileage", json=mileage, headers=eng_headers)
    assert r.status_code == 403

    # Взял тикет в работу — может менять.
    queue.assigned_engineer_id = engineer.id
    queue.status = TicketStatus.IN_PROGRESS
    db.commit()
    r = client.patch(f"{API}/vehicles/{vid}/mileage", json=mileage, headers=eng_headers)
    assert r.status_code == 200

    # Тикет решён: история видна, изменения — нет.
    queue.status = TicketStatus.RESOLVED
    queue.resolved_at = datetime.now(UTC)
    db.commit()
    assert client.get(f"{API}/vehicles/{vid}", headers=eng_headers).status_code == 200
    r = client.post(
        f"{API}/vehicles/{vid}/maintenance-records",
        json={"performed_at": "2026-01-10", "mileage_at_service": 1, "description": "x"},
        headers=eng_headers,
    )
    assert r.status_code == 403


def test_deleted_vehicle_visible_to_staff_by_ticket(client, as_client, as_staff, make_ticket):
    owner = as_client("+375291100101")
    vid = add_vehicle(client, owner)["id"]
    eng_headers, engineer = as_staff("+375291100102")
    admin_headers, _ = as_staff("+375291100103", UserRole.ADMIN)
    make_ticket(vid, engineer)
    assert client.delete(f"{API}/vehicles/{vid}", headers=owner).status_code == 204

    for headers in (eng_headers, admin_headers):
        r = client.get(f"{API}/vehicles/{vid}", headers=headers)
        assert r.status_code == 200
        assert r.json()["is_active"] is False
    assert client.get(f"{API}/vehicles/{vid}", headers=owner).status_code == 404


def test_admin_deletes_any_vehicle(client, as_client, as_staff):
    owner = as_client("+375291100111")
    vid = add_vehicle(client, owner)["id"]
    admin_headers, _ = as_staff("+375291100112", UserRole.ADMIN)
    assert client.delete(f"{API}/vehicles/{vid}", headers=admin_headers).status_code == 204
    assert client.get(f"{API}/vehicles", headers=owner).json()["items"] == []


def test_deleted_vehicle_is_read_only(client, as_client, as_staff, make_ticket):
    """Удалённое авто видно персоналу по тикету, но не изменяется никем (ADR 0014)."""
    owner = as_client("+375291100121")
    vid = add_vehicle(client, owner)["id"]
    eng_headers, engineer = as_staff("+375291100122")
    admin_headers, _ = as_staff("+375291100123", UserRole.ADMIN)
    make_ticket(vid, engineer)  # тикет в работе: до удаления инженер мог бы менять
    assert client.delete(f"{API}/vehicles/{vid}", headers=owner).status_code == 204

    url = f"{API}/vehicles/{vid}"
    mileage = ("patch", f"{url}/mileage", {"mileage": 10}, "updateVehicleMileage")
    record = (
        "post",
        f"{url}/maintenance-records",
        {"performed_at": "2026-01-10", "mileage_at_service": 1, "description": "x"},
        "createMaintenanceRecord",
    )
    correction = (
        "post",
        f"{url}/mileage-corrections",
        {"expected_current_mileage": 0, "mileage": 0, "reason": "x"},
        "correctVehicleMileage",
    )
    delete = ("delete", url, None, "deleteVehicle")
    expected = [
        (eng_headers, mileage, 403),
        (eng_headers, record, 403),
        (admin_headers, mileage, 403),
        (admin_headers, record, 403),
        (admin_headers, correction, 403),
        (admin_headers, delete, 403),
        (owner, mileage, 404),  # клиенту удалённое авто не видно
        (owner, delete, 404),
    ]
    for headers, (method, path, body, operation_id), status in expected:
        r = client.request(method, path, json=body, headers=headers)
        assert r.status_code == status, (operation_id, r.text)
        if status == 403:
            assert r.json()["error"]["message"] == "Автомобиль удалён — изменения недоступны"


def test_change_check_is_one_query(as_client, client, as_staff, make_ticket, db):
    """Успешная проверка изменения — один запрос: авто под блокировкой + тикет-основание."""
    owner = as_client("+375291100131")
    vid = add_vehicle(client, owner)["id"]
    _, engineer = as_staff("+375291100132")
    ticket = make_ticket(vid, engineer)

    statements: list[str] = []
    connection = db.connection()
    listener = lambda *args: statements.append(args[2])  # noqa: E731
    event.listen(connection, "before_cursor_execute", listener)
    try:
        vehicle, ticket_id = access.for_change(db, engineer, vid)
    finally:
        event.remove(connection, "before_cursor_execute", listener)
    assert (vehicle.id, ticket_id) == (vid, ticket.id)
    assert len(statements) == 1 and "FOR UPDATE OF vehicle" in statements[0]


# ---------- RBAC и аутентификация (контракт с Auth Service) ----------

VEHICLE_CALLS = [
    ("get", "/vehicle-models", None),
    ("get", "/vehicles", None),
    ("post", "/vehicles", {"vin": ZEEKR_VIN}),
    ("get", "/vehicles/1", None),
    ("delete", "/vehicles/1", None),
    ("patch", "/vehicles/1/mileage", {"mileage": 1}),
    (
        "post",
        "/vehicles/1/mileage-corrections",
        {"expected_current_mileage": 1, "mileage": 0, "reason": "x"},
    ),
    ("get", "/vehicles/1/maintenance-records", None),
    (
        "post",
        "/vehicles/1/maintenance-records",
        {"performed_at": "2026-01-01", "mileage_at_service": 1},
    ),
]


@pytest.mark.parametrize(("method", "path", "body"), VEHICLE_CALLS)
@pytest.mark.parametrize("token", [None, "not-a-jwt"], ids=["no-token", "bad-token"])
def test_vehicle_endpoints_require_valid_token(client, method, path, body, token):
    headers = bearer(token) if token else {}
    r = client.request(method, f"{API}{path}", json=body, headers=headers)
    assert r.status_code == 401
    assert r.headers["WWW-Authenticate"] == "Bearer"
    assert r.json()["error"]["code"] == "UNAUTHORIZED"


def test_roles_outside_matrix_get_403(client, as_client, as_staff):
    owner = as_client("+375291100121")
    vid = add_vehicle(client, owner)["id"]
    eng_headers, _ = as_staff("+375291100122")

    denied = [
        (
            owner,
            "post",
            f"/vehicles/{vid}/mileage-corrections",
            {"expected_current_mileage": 0, "mileage": 0, "reason": "x"},
        ),
        (
            owner,
            "post",
            f"/vehicles/{vid}/maintenance-records",
            {"performed_at": "2026-01-01", "mileage_at_service": 1, "description": "x"},
        ),
        (eng_headers, "delete", f"/vehicles/{vid}", None),
        (eng_headers, "get", "/vehicles", None),
        (eng_headers, "post", "/vehicles", {"vin": "L6TZ0010000000009"}),
    ]
    for headers, method, path, body in denied:
        r = client.request(method, f"{API}{path}", json=body, headers=headers)
        assert r.status_code == 403, f"{method} {path}"
        assert r.json()["error"]["code"] == "FORBIDDEN"


# ---------- Исправление пробега (ADR 0006) ----------


def test_admin_mileage_correction(client, as_client, as_staff, db):
    owner = as_client("+375291100131")
    vid = add_vehicle(client, owner)["id"]
    client.patch(f"{API}/vehicles/{vid}/mileage", json={"mileage": 50000}, headers=owner)
    admin_headers, admin = as_staff("+375291100132", UserRole.ADMIN)
    url = f"{API}/vehicles/{vid}/mileage-corrections"

    r = client.post(
        url,
        json={"expected_current_mileage": 49000, "mileage": 5000, "reason": "Опечатка"},
        headers=admin_headers,
    )
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "MILEAGE_CORRECTION_STALE"

    r = client.post(
        url,
        json={"expected_current_mileage": 50000, "mileage": 50000, "reason": "Опечатка"},
        headers=admin_headers,
    )
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "MILEAGE_NOT_DECREASED"

    r = client.post(
        url,
        json={"expected_current_mileage": 50000, "mileage": 5000, "reason": "  Опечатка  "},
        headers=admin_headers,
    )
    assert r.status_code == 201, r.text
    assert r.json()["mileage"] == 5000
    entry = db.scalars(
        select(VehicleMileageCorrection).where(VehicleMileageCorrection.vehicle_id == vid)
    ).one()
    assert (entry.old_mileage, entry.new_mileage, entry.reason) == (50000, 5000, "Опечатка")
    assert entry.corrected_by_user_id == admin.id

    r = client.post(
        url,
        json={"expected_current_mileage": 5000, "mileage": 1, "reason": "   "},
        headers=admin_headers,
    )
    assert r.status_code == 422


# ---------- История работ ----------


def test_maintenance_record_rules(client, as_client, as_staff, make_ticket, db):
    owner = as_client("+375291100141")
    vid = add_vehicle(client, owner)["id"]
    client.patch(f"{API}/vehicles/{vid}/mileage", json={"mileage": 30000}, headers=owner)
    eng_headers, engineer = as_staff("+375291100142")
    admin_headers, _ = as_staff("+375291100143", UserRole.ADMIN)
    older = make_ticket(vid, engineer)
    newer = make_ticket(vid, engineer, TicketStatus.WAITING_VENDOR)
    url = f"{API}/vehicles/{vid}/maintenance-records"
    tomorrow = (datetime.now(BUSINESS_TZ).date() + timedelta(days=1)).isoformat()

    cases = [
        (
            {"performed_at": tomorrow, "mileage_at_service": 1, "description": "x"},
            "PERFORMED_AT_IN_FUTURE",
        ),
        (
            {"performed_at": "2026-01-01", "mileage_at_service": 1, "aggregate_type_code": "nope"},
            "AGGREGATE_TYPE_NOT_FOUND",
        ),
        (
            {"performed_at": "2026-01-01", "mileage_at_service": 1, "description": "   "},
            "MAINTENANCE_SUBJECT_REQUIRED",
        ),
        (
            {"performed_at": "2026-01-01", "mileage_at_service": -1, "description": "x"},
            "VALIDATION_ERROR",
        ),
    ]
    for body, code in cases:
        r = client.post(url, json=body, headers=eng_headers)
        assert r.status_code == 422, body
        assert r.json()["error"]["code"] == code

    # Запись задним числом: пробег авто не уменьшается; связь с последним тикетом инженера.
    r = client.post(
        url,
        json={
            "performed_at": "2025-06-01",
            "mileage_at_service": 10000,
            "aggregate_type_code": "engine_oil",
        },
        headers=eng_headers,
    )
    assert r.status_code == 201
    assert "description" in r.json() and r.json()["description"] is None
    record = db.get(MaintenanceRecord, r.json()["id"])
    assert record.ticket_id == newer.id != older.id
    assert db.get(Vehicle, vid).mileage == 30000

    r = client.post(
        url,
        json={"performed_at": "2025-07-01", "mileage_at_service": 11000, "description": "Ремонт"},
        headers=admin_headers,
    )
    assert r.status_code == 201
    assert db.get(MaintenanceRecord, r.json()["id"]).ticket_id is None

    page = client.get(url, headers=owner).json()
    assert [i["performed_at"] for i in page["items"]] == ["2025-07-01", "2025-06-01"]


def test_record_without_author_omits_performed_by(client, as_client, db):
    """performed_by не nullable в контракте: без автора поле опускается, а не равно null;
    nullable aggregate_type_code и description при этом выводятся как null."""
    owner = as_client("+375291100151")
    vid = add_vehicle(client, owner)["id"]
    oil = db.scalars(select(AggregateType).where(AggregateType.code == "engine_oil")).one()
    db.add_all(
        [
            MaintenanceRecord(
                vehicle_id=vid,
                performed_at=date(2026, 1, 2),
                mileage_at_service=0,
                description="Импорт",
            ),
            MaintenanceRecord(
                vehicle_id=vid,
                aggregate_type_id=oil.id,
                performed_at=date(2026, 1, 1),
                mileage_at_service=0,
            ),
        ]
    )
    db.commit()
    r = client.get(f"{API}/vehicles/{vid}/maintenance-records", headers=owner)
    imported, oil_change = r.json()["items"]
    assert "performed_by" not in imported and "performed_by" not in oil_change
    assert imported["aggregate_type_code"] is None and imported["description"] == "Импорт"
    assert oil_change["aggregate_type_code"] == "engine_oil" and oil_change["description"] is None


# ---------- Лимит добавления (ADR 0014, Q11) ----------


def test_vehicle_create_rate_limited(client, as_client, settings: Settings):
    owner = as_client("+375291100161")
    for _ in range(settings.vehicle_create_per_user_hour):
        r = client.post(f"{API}/vehicles", json={"vin": UNKNOWN_VIN}, headers=owner)
        assert r.status_code == 422  # попытки перебора считаются, даже неуспешные
    r = client.post(f"{API}/vehicles", json={"vin": UNKNOWN_VIN}, headers=owner)
    assert r.status_code == 429
    assert 0 < int(r.headers["Retry-After"]) <= 3600

    other = as_client("+375291100162")
    assert client.post(f"{API}/vehicles", json={"vin": ZEEKR_VIN}, headers=other).status_code == 201


@pytest.mark.parametrize("vehicle_id", [0, -1, 2**63, 10**20])
def test_out_of_range_vehicle_id_is_404(client, as_client, vehicle_id):
    owner = as_client("+375291100171")
    r = client.get(f"{API}/vehicles/{vehicle_id}", headers=owner)
    assert r.status_code == 404
