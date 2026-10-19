"""Aggregates & Maintenance Service (Глава 12, ADR 0016): API, доступ, целостность истории.

Токены — настоящие (Глава 10), тикеты создаются в БД (Глава 13). Каждый ответ сверяется
со схемой docs/openapi.yaml (`assert_contract`). Сценарии главы 5 через сервис и БД —
tests/api/test_aggregate_scenarios.py.
"""

from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.time import today_in_business_tz
from app.models import (
    AppUser,
    MaintenanceRecord,
    MaintenanceRegulation,
    VehicleAggregateStatus,
)
from app.models.enums import TicketStatus, UserRole
from tests.api.conftest import API, add_vehicle, model_id

Headers = dict[str, str]


@pytest.fixture
def admin(as_staff) -> Headers:
    return as_staff("+375292200001", UserRole.ADMIN)[0]


@pytest.fixture
def engineer(as_staff) -> tuple[Headers, AppUser]:
    return as_staff("+375292200002")


def revise(client: TestClient, admin: Headers, **body) -> dict:
    r = client.post(f"{API}/maintenance-regulations", json=body, headers=admin)
    assert r.status_code == 201, r.text
    return r.json()


def statuses(client: TestClient, headers: Headers, vid: int, **params) -> dict:
    r = client.get(f"{API}/vehicles/{vid}/aggregate-statuses", params=params, headers=headers)
    assert r.status_code == 200, r.text
    return r.json()


def by_code(body: dict) -> dict[str, dict]:
    return {s["aggregate_type_code"]: s for s in body["items"]}


def replace(client: TestClient, headers: Headers, vid: int, code: str, **body):
    r = client.post(
        f"{API}/vehicles/{vid}/aggregate-statuses/{code}/replace", json=body, headers=headers
    )
    return r


def set_mileage(client: TestClient, headers: Headers, vid: int, mileage: int) -> None:
    r = client.patch(f"{API}/vehicles/{vid}/mileage", json={"mileage": mileage}, headers=headers)
    assert r.status_code == 200, r.text


TODAY = today_in_business_tz


# ---------- Интеграционный тест чек-листа: замена инженером → статус клиента сразу 🟢 ----------


def test_engineer_replacement_turns_client_status_green(
    client, as_client, admin, engineer, make_ticket, db: Session
):
    owner = as_client("+375292210001")
    vehicle = add_vehicle(client, owner)
    vid = vehicle["id"]
    zeekr = model_id(client, owner, "Zeekr")
    revise(
        client, admin, vehicle_model_id=zeekr, aggregate_type_code="engine_oil", interval_km=10000
    )
    revise(
        client,
        admin,
        vehicle_model_id=zeekr,
        aggregate_type_code="cabin_filter",
        interval_months=12,
    )

    set_mileage(client, owner, vid, 21000)
    body = statuses(client, owner, vid)
    assert [s["aggregate_type_code"] for s in body["items"]] == ["engine_oil", "cabin_filter"]
    assert {s["status"] for s in body["items"]} == {"unknown"}, "без истории замен — unknown (E1)"

    eng_headers, eng = engineer
    ticket = make_ticket(vid, eng)
    replace(
        client,
        eng_headers,
        vid,
        "engine_oil",
        replaced_at=str(TODAY() - timedelta(days=400)),
        mileage_at_replacement=9000,
    )
    oil = by_code(statuses(client, owner, vid))["engine_oil"]
    assert oil["status"] == "red" and oil["percentage"] == 120.0 and oil["remaining_km"] == -2000

    r = replace(
        client,
        eng_headers,
        vid,
        "engine_oil",
        replaced_at=str(TODAY()),
        mileage_at_replacement=21000,
        description="Замена масла по тикету",
    )
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "green" and r.json()["percentage"] == 0.0

    oil = by_code(statuses(client, owner, vid))["engine_oil"]
    assert oil == {
        "aggregate_type_code": "engine_oil",
        "aggregate_type_name": "Масло двигателя",
        "status": "green",
        "percentage": 0.0,
        "last_replaced_at": str(TODAY()),
        "last_replaced_mileage": 21000,
        "remaining_km": 10000,
        "remaining_days": None,
    }

    r = client.get(f"{API}/vehicles/{vid}/maintenance-records", headers=owner)
    records = r.json()["items"]
    assert [(m["aggregate_type_code"], m["mileage_at_service"]) for m in records] == [
        ("engine_oil", 21000),
        ("engine_oil", 9000),
    ]
    assert records[0]["description"] == "Замена масла по тикету"
    assert records[0]["performed_by"]["id"] == eng.id
    assert db.get(MaintenanceRecord, records[0]["id"]).ticket_id == ticket.id

    set_mileage(client, owner, vid, 28000)
    assert by_code(statuses(client, owner, vid))["engine_oil"]["status"] == "yellow"


# ---------- Замена агрегата: правила ADR 0016 п. 2 ----------


@pytest.fixture
def staffed_vehicle(client, as_client, admin, engineer, make_ticket):
    """Авто Zeekr с пробегом 20 000, регламент масла 10 000 км, тикет инженера в работе."""
    owner = as_client("+375292220001")
    vid = add_vehicle(client, owner)["id"]
    set_mileage(client, owner, vid, 20000)
    revise(
        client,
        admin,
        vehicle_model_id=model_id(client, owner, "Zeekr"),
        aggregate_type_code="engine_oil",
        interval_km=10000,
    )
    make_ticket(vid, engineer[1])
    return owner, vid


def test_replace_rejects_future_date_and_mileage_ahead(client, engineer, staffed_vehicle):
    _, vid = staffed_vehicle
    eng = engineer[0]
    r = replace(
        client,
        eng,
        vid,
        "engine_oil",
        replaced_at=str(TODAY() + timedelta(days=1)),
        mileage_at_replacement=1,
    )
    assert r.status_code == 422 and r.json()["error"]["code"] == "REPLACED_AT_IN_FUTURE"

    r = replace(
        client, eng, vid, "engine_oil", replaced_at=str(TODAY()), mileage_at_replacement=20001
    )
    assert r.status_code == 409
    assert r.json()["error"] == {
        "code": "MILEAGE_AHEAD_OF_VEHICLE",
        "message": "Пробег замены больше пробега авто — сначала обновите пробег",
        "details": {"current_mileage": 20000},
    }

    r = replace(
        client, eng, vid, "no_such_part", replaced_at=str(TODAY()), mileage_at_replacement=1
    )
    assert r.status_code == 404 and r.json()["error"]["code"] == "AGGREGATE_TYPE_NOT_FOUND"

    r = replace(client, eng, vid, "engine_oil", replaced_at="2026-01-01", mileage_at_replacement=-1)
    assert r.status_code == 422


def test_backdated_replacement_goes_to_history_only(client, engineer, staffed_vehicle, db):
    owner, vid = staffed_vehicle
    eng = engineer[0]
    assert (
        replace(
            client, eng, vid, "engine_oil", replaced_at=str(TODAY()), mileage_at_replacement=18000
        ).status_code
        == 200
    )

    r = replace(
        client,
        eng,
        vid,
        "engine_oil",
        replaced_at=str(TODAY() - timedelta(days=30)),
        mileage_at_replacement=15000,
    )
    assert r.status_code == 200
    assert r.json()["last_replaced_mileage"] == 18000, "E6: ответ — прежний статус"
    assert r.json()["percentage"] == 20.0
    assert by_code(statuses(client, owner, vid))["engine_oil"]["last_replaced_mileage"] == 18000
    count = db.scalar(select(func.count()).where(MaintenanceRecord.vehicle_id == vid))
    assert count == 2, "обе замены — в истории ТО"

    # Повтор того же запроса: вторая запись в истории, текущая замена та же (E7, ADR 0016 п. 2).
    for _ in range(2):
        r = replace(
            client, eng, vid, "engine_oil", replaced_at=str(TODAY()), mileage_at_replacement=18000
        )
        assert r.status_code == 200 and r.json()["last_replaced_mileage"] == 18000
    assert db.scalar(select(func.count()).where(MaintenanceRecord.vehicle_id == vid)) == 4


def test_replacement_without_regulation_is_recorded_as_unknown(
    client, admin, engineer, staffed_vehicle
):
    owner, vid = staffed_vehicle
    r = replace(
        client,
        engineer[0],
        vid,
        "cabin_filter",
        replaced_at=str(TODAY() - timedelta(days=200)),
        mileage_at_replacement=12000,
    )
    assert r.status_code == 200
    assert r.json() == {
        "aggregate_type_code": "cabin_filter",
        "aggregate_type_name": "Салонный фильтр",
        "status": "unknown",
        "percentage": None,
        "last_replaced_at": str(TODAY() - timedelta(days=200)),
        "last_replaced_mileage": 12000,
        "remaining_km": None,
        "remaining_days": None,
    }
    assert "cabin_filter" not in by_code(statuses(client, owner, vid)), "нет регламента — нет узла"

    zeekr = model_id(client, owner, "Zeekr")
    revise(
        client, admin, vehicle_model_id=zeekr, aggregate_type_code="cabin_filter", interval_km=10000
    )
    cabin = by_code(statuses(client, owner, vid))["cabin_filter"]
    assert cabin["status"] == "yellow" and cabin["percentage"] == 80.0
    assert cabin["last_replaced_mileage"] == 12000, "замена до регламента не потеряна"


def test_maintenance_record_with_aggregate_does_not_reset_counter(
    client, engineer, staffed_vehicle
):
    """ADR 0016 п. 1: счётчик сбрасывает только замена агрегата."""
    owner, vid = staffed_vehicle
    r = client.post(
        f"{API}/vehicles/{vid}/maintenance-records",
        json={
            "aggregate_type_code": "engine_oil",
            "performed_at": str(TODAY()),
            "mileage_at_service": 20000,
        },
        headers=engineer[0],
    )
    assert r.status_code == 201
    assert r.json()["kind"] == "work"
    assert by_code(statuses(client, owner, vid))["engine_oil"]["status"] == "unknown"


def test_aggregate_history_tells_replacement_from_work(client, engineer, staffed_vehicle):
    """ADR 0023 п. 2: история агрегата — замены и работы по нему, у записи kind."""
    owner, vid = staffed_vehicle
    eng = engineer[0]
    r = replace(
        client,
        eng,
        vid,
        "engine_oil",
        replaced_at=str(TODAY() - timedelta(days=10)),
        mileage_at_replacement=15000,
    )
    assert r.status_code == 200
    for code, description in (("engine_oil", "Долив"), ("air_filter", "Осмотр"), (None, "Мойка")):
        r = client.post(
            f"{API}/vehicles/{vid}/maintenance-records",
            json={
                "aggregate_type_code": code,
                "performed_at": str(TODAY()),
                "mileage_at_service": 16000,
                "description": description,
            },
            headers=eng,
        )
        assert r.status_code == 201

    def history(**params) -> list[tuple[str | None, str, str | None]]:
        r = client.get(f"{API}/vehicles/{vid}/maintenance-records", params=params, headers=owner)
        assert r.status_code == 200, r.text
        return [(i["aggregate_type_code"], i["kind"], i["description"]) for i in r.json()["items"]]

    assert history(aggregate_type_code="engine_oil") == [
        ("engine_oil", "work", "Долив"),
        ("engine_oil", "replacement", None),
    ], "новые сверху, только по агрегату"
    assert [kind for _, kind, _ in history()] == ["work", "work", "work", "replacement"]
    assert history(aggregate_type_code="no_such_aggregate") == [], "фильтр, а не ошибка"
    assert by_code(statuses(client, owner, vid))["engine_oil"]["last_replaced_mileage"] == 15000


# ---------- Доступ к замене: как изменение авто (ADR 0014 п. 4) ----------


def test_replace_access(client, as_client, as_staff, admin, make_ticket, db):
    owner = as_client("+375292230001")
    vid = add_vehicle(client, owner)["id"]
    body = {"replaced_at": str(TODAY()), "mileage_at_replacement": 0}

    r = client.post(
        f"{API}/vehicles/{vid}/aggregate-statuses/engine_oil/replace", json=body, headers=owner
    )
    assert r.status_code == 403, "клиент не фиксирует замену (RBAC)"

    stranger, _ = as_staff("+375292230002")
    assert replace(client, stranger, vid, "engine_oil", **body).status_code == 404, "без тикета"

    queued, queued_user = as_staff("+375292230003")
    make_ticket(vid)  # очередь: видно, но менять нельзя
    assert replace(client, queued, vid, "engine_oil", **body).status_code == 403

    closed, closed_user = as_staff("+375292230004")
    make_ticket(vid, closed_user, TicketStatus.RESOLVED)
    assert replace(client, closed, vid, "engine_oil", **body).status_code == 403

    assert replace(client, admin, vid, "engine_oil", **body).status_code == 200
    record = db.scalars(select(MaintenanceRecord).where(MaintenanceRecord.vehicle_id == vid)).one()
    assert record.ticket_id is None, "у админа тикета-основания нет"

    assert client.delete(f"{API}/vehicles/{vid}", headers=owner).status_code == 204
    r = replace(client, admin, vid, "engine_oil", **body)
    assert r.status_code == 403, "удалённое авто не изменяется никем"


def test_statuses_access(client, as_client, as_staff, make_ticket, admin):
    owner = as_client("+375292240001")
    vid = add_vehicle(client, owner)["id"]
    other = as_client("+375292240002")
    r = client.get(f"{API}/vehicles/{vid}/aggregate-statuses", headers=other)
    assert r.status_code == 404

    eng, _ = as_staff("+375292240003")
    assert client.get(f"{API}/vehicles/{vid}/aggregate-statuses", headers=eng).status_code == 404
    make_ticket(vid)  # очередь — просмотр карточки
    statuses(client, eng, vid)
    statuses(client, admin, vid)

    r = client.get(f"{API}/vehicles/{10**20}/aggregate-statuses", headers=admin)
    assert r.status_code == 404


def test_statuses_pagination_in_schema_order(client, as_client, admin):
    owner = as_client("+375292250001")
    vid = add_vehicle(client, owner)["id"]
    zeekr = model_id(client, owner, "Zeekr")
    for code in ("ac_refrigerant", "engine_oil", "air_filter"):
        revise(client, admin, vehicle_model_id=zeekr, aggregate_type_code=code, interval_months=24)
    body = statuses(client, owner, vid, page=2, page_size=2)
    assert body["meta"] == {"page": 2, "page_size": 2, "total_items": 3, "total_pages": 2}
    assert [s["aggregate_type_code"] for s in body["items"]] == ["ac_refrigerant"]
    body = statuses(client, owner, vid)
    assert [s["aggregate_type_code"] for s in body["items"]] == [
        "engine_oil",
        "air_filter",
        "ac_refrigerant",
    ]


# ---------- Регламенты ТО: версии и целостность истории ----------


def test_revision_and_archive_keep_history(client, admin, engineer, staffed_vehicle, db):
    """Тест чек-листа: удаление (архивирование) регламента не ломает историю (E8, E9)."""
    owner, vid = staffed_vehicle
    zeekr = model_id(client, owner, "Zeekr")
    eng = engineer[0]
    assert (
        replace(
            client, eng, vid, "engine_oil", replaced_at=str(TODAY()), mileage_at_replacement=15000
        ).status_code
        == 200
    )
    assert by_code(statuses(client, owner, vid))["engine_oil"]["percentage"] == 50.0

    v1 = client.get(
        f"{API}/maintenance-regulations", params={"vehicle_model_id": zeekr}, headers=admin
    ).json()["items"]
    [old] = [r for r in v1 if r["aggregate_type_code"] == "engine_oil"]
    new = revise(
        client, admin, vehicle_model_id=zeekr, aggregate_type_code="engine_oil", interval_km=5000
    )
    assert new["id"] != old["id"] and new["is_archived"] is False
    assert (
        by_code(statuses(client, owner, vid))["engine_oil"]["status"] == "yellow"
    ), "E8: новая версия"

    r = client.get(
        f"{API}/maintenance-regulations",
        params={"vehicle_model_id": zeekr, "include_archived": True},
        headers=eng,
    )
    oil = [
        (x["id"], x["interval_km"], x["is_archived"])
        for x in r.json()["items"]
        if x["aggregate_type_code"] == "engine_oil"
    ]
    assert oil == [(new["id"], 5000, False), (old["id"], 10000, True)], "новые версии первыми"

    same = revise(
        client, admin, vehicle_model_id=zeekr, aggregate_type_code="engine_oil", interval_km=5000
    )
    assert same["id"] != new["id"], "пересмотр с теми же интервалами — новая версия (ADR 0016 п. 3)"

    r = client.delete(f"{API}/maintenance-regulations/{same['id']}", headers=admin)
    assert r.status_code == 204
    assert "engine_oil" not in by_code(statuses(client, owner, vid)), "E9: узел пропал"
    assert db.scalar(select(func.count()).where(MaintenanceRecord.vehicle_id == vid)) == 1
    kept = db.scalars(
        select(VehicleAggregateStatus).where(VehicleAggregateStatus.vehicle_id == vid)
    ).one()
    assert kept.last_replaced_mileage == 15000
    archived = db.scalar(
        select(func.count()).where(
            MaintenanceRegulation.vehicle_model_id == zeekr,
            MaintenanceRegulation.is_archived.is_(True),
        )
    )
    assert archived == 3

    for regulation_id in (same["id"], old["id"], 10**9, 10**20):
        r = client.delete(f"{API}/maintenance-regulations/{regulation_id}", headers=admin)
        assert r.status_code == 404, regulation_id
        assert r.json()["error"]["code"] == "REGULATION_NOT_FOUND"

    revise(
        client, admin, vehicle_model_id=zeekr, aggregate_type_code="engine_oil", interval_km=10000
    )
    assert (
        by_code(statuses(client, owner, vid))["engine_oil"]["percentage"] == 50.0
    ), "замена сохранилась"


@pytest.mark.parametrize(
    ("body", "code"),
    [
        (
            {"vehicle_model_id": 10**9, "aggregate_type_code": "engine_oil", "interval_km": 500},
            "VEHICLE_MODEL_NOT_FOUND",
        ),
        ({"aggregate_type_code": "no_such_part", "interval_km": 500}, "AGGREGATE_TYPE_NOT_FOUND"),
        ({"aggregate_type_code": "engine_oil"}, "VALIDATION_ERROR"),
        ({"aggregate_type_code": "engine_oil", "interval_km": 0}, "VALIDATION_ERROR"),
        # #105 (№13): меньше 500 км — опечатка, а не регламент.
        ({"aggregate_type_code": "engine_oil", "interval_km": 1}, "VALIDATION_ERROR"),
        ({"aggregate_type_code": "engine_oil", "interval_km": 499}, "VALIDATION_ERROR"),
        ({"aggregate_type_code": "engine_oil", "interval_months": 1201}, "VALIDATION_ERROR"),
        (
            {"vehicle_model_id": 2**63, "aggregate_type_code": "engine_oil", "interval_km": 1},
            "VALIDATION_ERROR",
        ),
    ],
)
def test_revise_validation(client, as_client, admin, body, code):
    owner = as_client("+375292260001")
    body = {"vehicle_model_id": model_id(client, owner, "Zeekr")} | body
    r = client.post(f"{API}/maintenance-regulations", json=body, headers=admin)
    assert r.status_code == 422, r.text
    assert r.json()["error"]["code"] == code


def test_regulation_version_has_date_and_author(client, as_client, as_staff, engineer):
    """#105 (U-44): у версии регламента — дата и автор; инженер видит только id автора."""
    admin_headers, admin_user = as_staff("+375292280002", UserRole.ADMIN)
    owner = as_client("+375292280001")
    model = model_id(client, owner, "Zeekr")
    body = {"vehicle_model_id": model, "aggregate_type_code": "engine_oil", "interval_km": 500}
    r = client.post(f"{API}/maintenance-regulations", json=body, headers=admin_headers)
    assert r.status_code == 201, r.text
    created = r.json()
    assert created["created_by_user_id"] == admin_user.id
    assert datetime.fromisoformat(created["created_at"]) > datetime.now(UTC) - timedelta(minutes=5)
    r = client.get(
        f"{API}/maintenance-regulations", params={"vehicle_model_id": model}, headers=engineer[0]
    )
    seen = next(item for item in r.json()["items"] if item["id"] == created["id"])
    assert (seen["created_by_user_id"], "created_by" in seen) == (admin_user.id, False)


def test_regulations_rbac(client, as_client, engineer):
    owner = as_client("+375292270001")
    r = client.get(f"{API}/maintenance-regulations", headers=owner)
    assert r.status_code == 403
    body = {"vehicle_model_id": 1, "aggregate_type_code": "engine_oil", "interval_km": 1}
    r = client.post(f"{API}/maintenance-regulations", json=body, headers=engineer[0])
    assert r.status_code == 403
    r = client.delete(f"{API}/maintenance-regulations/1", headers=engineer[0])
    assert r.status_code == 403


# ---------- Справочник агрегатов ----------


def test_aggregate_types_catalog(client, as_client, admin, engineer):
    owner = as_client("+375292280001")
    r = client.get(f"{API}/aggregate-types", headers=owner)
    assert [t["code"] for t in r.json()["items"]] == [
        "engine_oil",
        "oil_filter",
        "air_filter",
        "cabin_filter",
        "gearbox_oil",
        "ac_refrigerant",
    ]

    body = {"code": "brake_fluid", "name": "  Тормозная жидкость "}
    r = client.post(f"{API}/aggregate-types", json=body, headers=admin)
    assert r.status_code == 201
    assert r.json() == {"code": "brake_fluid", "name": "Тормозная жидкость"}

    r = client.post(f"{API}/aggregate-types", json=body, headers=admin)
    assert r.status_code == 409 and r.json()["error"]["code"] == "AGGREGATE_TYPE_EXISTS"

    for bad in (
        {"code": "Brake", "name": "x"},
        {"code": "b", "name": "x"},
        {"code": "brake2", "name": " "},
    ):
        r = client.post(f"{API}/aggregate-types", json=bad, headers=admin)
        assert r.status_code == 422, bad

    r = client.post(
        f"{API}/aggregate-types", json={"code": "x_part", "name": "x"}, headers=engineer[0]
    )
    assert r.status_code == 403

    r = client.get(f"{API}/aggregate-types", params={"page_size": 100}, headers=owner)
    assert r.json()["items"][-1]["code"] == "brake_fluid"


# ---------- Пороги «светофора» ----------


def test_thresholds(client, admin, engineer, staffed_vehicle, as_staff):
    owner, vid = staffed_vehicle
    eng = engineer[0]
    replace(client, eng, vid, "engine_oil", replaced_at=str(TODAY()), mileage_at_replacement=14000)

    r = client.get(f"{API}/aggregate-status-thresholds", headers=eng)
    assert r.json()["yellow_from_percent"] == 70 and r.json()["red_above_percent"] == 100
    assert by_code(statuses(client, owner, vid))["engine_oil"]["status"] == "green"  # 60%

    r = client.put(
        f"{API}/aggregate-status-thresholds",
        json={"yellow_from_percent": 50, "red_above_percent": 55},
        headers=admin,
    )
    assert r.status_code == 200
    admin_id = client.get(f"{API}/me", headers=admin).json()["id"]
    assert r.json()["updated_by_user_id"] == admin_id
    assert by_code(statuses(client, owner, vid))["engine_oil"]["status"] == "red", "E10: сразу"

    for bad in (
        {"yellow_from_percent": 80, "red_above_percent": 80},
        {"yellow_from_percent": 0, "red_above_percent": 80},
        {"yellow_from_percent": 70, "red_above_percent": 201},
    ):
        r = client.put(f"{API}/aggregate-status-thresholds", json=bad, headers=admin)
        assert r.status_code == 422, bad

    r = client.put(
        f"{API}/aggregate-status-thresholds",
        json={"yellow_from_percent": 70, "red_above_percent": 100},
        headers=eng,
    )
    assert r.status_code == 403
    assert client.get(f"{API}/aggregate-status-thresholds", headers=owner).status_code == 403
