"""Гонки Aggregates Service (Глава 12, ADR 0016): параллельные запросы на отдельных соединениях.

- Пересмотры одной пары «модель + агрегат» идут по очереди: все получают 201, активная версия
  ровно одна (без блокировки модели — нарушение uq_maintenance_regulation_active → 500).
- Замены одного агрегата идут по очереди (строка авто под FOR UPDATE): строка статуса одна,
  в истории — каждая замена, текущей становится замена с наибольшей датой.
"""

from collections.abc import Iterator
from datetime import date
from typing import NamedTuple

import pytest
from sqlalchemy import Engine, delete, func, select
from sqlalchemy.orm import Session

from app.domain.aggregates import service
from app.models import (
    AppUser,
    MaintenanceRecord,
    MaintenanceRegulation,
    Vehicle,
    VehicleAggregateStatus,
    VehicleModel,
)
from app.models.enums import UserRole
from tests.api.test_concurrency import storm

THREADS = 8


class World(NamedTuple):
    admin_id: int
    model_id: int
    vehicle_id: int


@pytest.fixture
def world(migrated_engine: Engine) -> Iterator[World]:
    with Session(migrated_engine) as setup:
        admin = AppUser(
            phone="+375292300001", role=UserRole.ADMIN, password_hash="$argon2id$test-only"
        )
        owner = AppUser(phone="+375292300002", role=UserRole.CLIENT)
        model = VehicleModel(brand="Race", model="R")
        setup.add_all([admin, owner, model])
        setup.flush()
        vehicle = Vehicle(
            user_id=owner.id, vehicle_model_id=model.id, vin="L6TZ0010000008888", mileage=50000
        )
        setup.add(vehicle)
        setup.commit()
        ids = World(admin.id, model.id, vehicle.id)
        users = (admin.id, owner.id)
    yield ids
    with Session(migrated_engine) as cleanup:
        cleanup.execute(
            delete(MaintenanceRecord).where(MaintenanceRecord.vehicle_id == ids.vehicle_id)
        )
        cleanup.execute(
            delete(VehicleAggregateStatus).where(
                VehicleAggregateStatus.vehicle_id == ids.vehicle_id
            )
        )
        cleanup.execute(delete(Vehicle).where(Vehicle.id == ids.vehicle_id))
        cleanup.execute(
            delete(MaintenanceRegulation).where(
                MaintenanceRegulation.vehicle_model_id == ids.model_id
            )
        )
        cleanup.execute(delete(VehicleModel).where(VehicleModel.id == ids.model_id))
        cleanup.execute(delete(AppUser).where(AppUser.id.in_(users)))
        cleanup.commit()


def test_parallel_revisions_leave_one_active_version(migrated_engine: Engine, world: World):
    turn = iter(range(100))

    def revise() -> object:
        km = 1000 * (next(turn) + 1)
        with Session(migrated_engine, expire_on_commit=False) as s:
            return service.revise_regulation(s, world.model_id, "engine_oil", km, None)

    results = storm(THREADS, revise)
    assert all(isinstance(r, MaintenanceRegulation) for r in results), results
    with Session(migrated_engine) as check:
        rows = check.scalars(
            select(MaintenanceRegulation).where(
                MaintenanceRegulation.vehicle_model_id == world.model_id
            )
        ).all()
    assert len(rows) == THREADS
    active = [r for r in rows if not r.is_archived]
    assert len(active) == 1
    assert active[0].id == max(r.id for r in rows), "побеждает последний пересмотр"


def test_parallel_replacements_keep_one_status_row(migrated_engine: Engine, world: World):
    turn = iter(range(100))

    def replace() -> object:
        day = next(turn) + 1
        with Session(migrated_engine, expire_on_commit=False) as s:
            return service.replace_aggregate(
                s,
                s.get_one(AppUser, world.admin_id),
                world.vehicle_id,
                "engine_oil",
                replaced_at=date(2026, 9, day),
                mileage_at_replacement=40000 + day,
                description=None,
                today=date(2026, 10, 10),
            )

    results = storm(THREADS, replace)
    assert not [r for r in results if isinstance(r, Exception)], results
    with Session(migrated_engine) as check:
        row = check.scalars(
            select(VehicleAggregateStatus).where(
                VehicleAggregateStatus.vehicle_id == world.vehicle_id
            )
        ).one()
        records = check.scalar(
            select(func.count()).where(MaintenanceRecord.vehicle_id == world.vehicle_id)
        )
    assert records == THREADS
    assert row.last_replaced_at == date(2026, 9, THREADS), "текущая — с наибольшей датой (E5)"
    assert row.last_replaced_mileage == 40000 + THREADS
