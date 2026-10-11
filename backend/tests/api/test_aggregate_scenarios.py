"""Сценарии главы 5 через сервис и PostgreSQL (DoD главы 12, ADR 0016 п. 6).

Тот же YAML, что у модульных тестов чистой функции (tests/domain/test_aggregate_status.py),
но входы лежат в таблицах: регламент — `maintenance_regulation`, последняя замена —
`vehicle_aggregate_status`, пробег — `vehicle`, пороги — `aggregate_status_thresholds`.
Так проверяется загрузка входов сервисом, а не только формула. `today` — из сценария.
"""

from decimal import Decimal

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.domain.aggregates import service
from app.models import (
    AggregateStatusThresholds,
    AggregateType,
    AppUser,
    MaintenanceRecord,
    MaintenanceRegulation,
    Vehicle,
    VehicleAggregateStatus,
    VehicleModel,
)
from app.models.enums import UserRole
from tests.domain.test_aggregate_status import DEFAULTS, SCENARIOS

CODE = "engine_oil"


@pytest.fixture
def admin(make_staff) -> AppUser:
    return make_staff("+375292290001", UserRole.ADMIN)


@pytest.fixture
def vehicle(db: Session, make_client_user) -> Vehicle:
    model = VehicleModel(brand="Scenario", model="S")
    db.add(model)
    db.flush()
    owner = make_client_user("+375292290002")
    vehicle = Vehicle(user_id=owner.id, vehicle_model_id=model.id, vin="L6TZ0010000005555")
    db.add(vehicle)
    db.commit()
    return vehicle


def _aggregate_type_id(db: Session) -> int:
    return db.scalar(select(AggregateType.id).where(AggregateType.code == CODE))


def _arrange(db: Session, vehicle: Vehicle, case: dict) -> None:
    type_id = _aggregate_type_id(db)
    if case["regulation"] is not None:
        db.add(
            MaintenanceRegulation(
                vehicle_model_id=vehicle.vehicle_model_id,
                aggregate_type_id=type_id,
                **case["regulation"],
            )
        )
    if case["last"] is not None:
        db.add(
            VehicleAggregateStatus(
                vehicle_id=vehicle.id,
                aggregate_type_id=type_id,
                last_replaced_at=case["last"].get("replaced_at"),
                last_replaced_mileage=case["last"].get("mileage"),
            )
        )
    thresholds = db.get_one(AggregateStatusThresholds, 1)
    for key, value in case.get("thresholds", DEFAULTS["thresholds"]).items():
        setattr(thresholds, key, value)
    vehicle.mileage = case["current_mileage"]
    db.commit()


@pytest.mark.parametrize("case", SCENARIOS["status"], ids=lambda c: c["id"])
def test_status_scenario_through_service(db: Session, vehicle: Vehicle, admin, case: dict):
    _arrange(db, vehicle, case)
    found, stmt = service.statuses_stmt(db, admin, vehicle.id)
    regulations = list(db.scalars(stmt))
    views = service.statuses_for(db, found, regulations, today=case.get("today", DEFAULTS["today"]))

    expect = case["expect"]
    if expect is None:
        assert views == [], "нет активного регламента — агрегат не возвращается (§2.1)"
        return
    [view] = views
    assert view.aggregate_type_code == CODE
    assert view.status.value == expect["status"]
    percentage = expect["percentage"]
    assert view.percentage == (None if percentage is None else Decimal(percentage))
    assert view.remaining_km == expect["remaining_km"]
    assert view.remaining_days == expect["remaining_days"]


@pytest.mark.parametrize("case", SCENARIOS["replacement"], ids=lambda c: c["id"])
def test_replacement_scenario_through_service(db: Session, vehicle: Vehicle, admin, case: dict):
    current, new = case["current"], case["new"]
    if current is not None:
        db.add(
            VehicleAggregateStatus(
                vehicle_id=vehicle.id,
                aggregate_type_id=_aggregate_type_id(db),
                last_replaced_at=current["replaced_at"],
                last_replaced_mileage=current["mileage"],
            )
        )
    vehicle.mileage = 30000
    db.commit()

    view = service.replace_aggregate(
        db,
        admin,
        vehicle.id,
        CODE,
        replaced_at=new["replaced_at"],
        mileage_at_replacement=new["mileage"],
        description=None,
        today=DEFAULTS["today"],
    )

    expected = new if case["becomes_current"] else current
    assert (view.last_replaced_at, view.last_replaced_mileage) == (
        expected["replaced_at"],
        expected["mileage"],
    )
    row = db.scalars(
        select(VehicleAggregateStatus).where(VehicleAggregateStatus.vehicle_id == vehicle.id)
    ).one()
    assert (row.last_replaced_at, row.last_replaced_mileage) == (
        expected["replaced_at"],
        expected["mileage"],
    )
    records = db.scalar(select(func.count()).where(MaintenanceRecord.vehicle_id == vehicle.id))
    assert records == 1, "история ТО пишется всегда (E5–E7)"
