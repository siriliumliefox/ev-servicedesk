"""Гонки Vehicle Service (Глава 11): параллельные запросы на отдельных соединениях PostgreSQL.

Проверка «VIN уже есть» и вставка не атомарны — последней линией защиты служит
uq_vehicle_vin_active; проигравший в гонке должен получить тот же 409, а не 500.
"""

import threading
from collections.abc import Iterator

import pytest
from redis import Redis
from sqlalchemy import Engine, delete, func, select, text
from sqlalchemy.orm import Session

from app.core.errors import ApiError
from app.domain.vehicles import service
from app.domain.vehicles.vin import MockVinDecoder
from app.models import AppUser, Vehicle
from app.models.enums import UserRole
from tests.api.conftest import api_settings
from tests.api.test_concurrency import storm

VIN = "L6TZ0010000000777"


@pytest.fixture
def two_clients(migrated_engine: Engine) -> Iterator[tuple[int, int]]:
    with Session(migrated_engine) as setup:
        users = [AppUser(phone=f"+37529777000{i}", role=UserRole.CLIENT) for i in (1, 2)]
        setup.add_all(users)
        setup.commit()
        ids = (users[0].id, users[1].id)
    yield ids
    with Session(migrated_engine) as cleanup:
        cleanup.execute(delete(Vehicle).where(Vehicle.user_id.in_(ids)))
        cleanup.execute(delete(AppUser).where(AppUser.id.in_(ids)))
        cleanup.commit()


def test_parallel_same_vin_creates_one_vehicle(
    migrated_engine: Engine, real_redis: Redis, two_clients: tuple[int, int]
):
    settings = api_settings()
    decoder = MockVinDecoder()
    turn = iter(range(100))

    def add() -> object:
        user_id = two_clients[next(turn) % 2]
        with Session(migrated_engine, expire_on_commit=False) as s:
            return service.create_vehicle(
                s, real_redis, settings, decoder, s.get(AppUser, user_id), VIN, None
            )

    results = storm(8, add)
    created = [r for r in results if isinstance(r, Vehicle)]
    conflicts = [r for r in results if isinstance(r, ApiError) and r.status_code == 409]
    assert len(created) == 1, results
    assert len(conflicts) == 7, results
    assert {c.code for c in conflicts} <= {"VIN_ALREADY_ADDED", "VIN_REGISTERED_TO_ANOTHER_ACCOUNT"}
    with Session(migrated_engine) as check:
        count = check.scalar(select(func.count()).select_from(Vehicle).where(Vehicle.vin == VIN))
    assert count == 1


def test_unique_index_race_maps_to_409(
    migrated_engine: Engine,
    real_redis: Redis,
    two_clients: tuple[int, int],
    monkeypatch: pytest.MonkeyPatch,
):
    """Все потоки проходят предварительную проверку — решает uq_vehicle_vin_active."""
    checked = threading.local()
    original = service._vin_conflict

    def stale_precheck(db, user, vin):
        if not getattr(checked, "done", False):
            checked.done = True
            return None  # как будто конкурент ещё не закоммитил
        return original(db, user, vin)

    monkeypatch.setattr(service, "_vin_conflict", stale_precheck)
    settings = api_settings()
    turn = iter(range(100))

    def add() -> object:
        user_id = two_clients[next(turn) % 2]
        with Session(migrated_engine, expire_on_commit=False) as s:
            return service.create_vehicle(
                s, real_redis, settings, MockVinDecoder(), s.get(AppUser, user_id), VIN, None
            )

    results = storm(6, add)
    assert sum(isinstance(r, Vehicle) for r in results) == 1, results
    assert all(
        isinstance(r, Vehicle) or (isinstance(r, ApiError) and r.status_code == 409)
        for r in results
    ), results


def test_open_reference_to_vehicle_does_not_block_mileage(
    migrated_engine: Engine, real_redis: Redis, two_clients: tuple[int, int]
):
    """Глава 24 (прогон k6): суточные напоминания о ТО — одна долгая транзакция, и вставки со
    ссылкой на авто держат FOR KEY SHARE до её конца. Изменение авто — FOR NO KEY UPDATE (ключ
    не меняется), поэтому обновление пробега не ждёт эту транзакцию (было — до минуты в 10:00).
    """
    user_id = two_clients[0]
    with Session(migrated_engine) as setup:
        vehicle = service.create_vehicle(
            setup,
            real_redis,
            api_settings(),
            MockVinDecoder(),
            setup.get(AppUser, user_id),
            VIN,
            None,
        )
        vehicle_id = vehicle.id
    with Session(migrated_engine) as holder, Session(migrated_engine) as writer:
        # Ссылка на авто в открытой транзакции — как запись напоминания (FK → FOR KEY SHARE).
        holder.execute(
            text(
                "INSERT INTO notification (type, vehicle_id, aggregate_type_id, message)"
                " SELECT 'maintenance', :v, min(id), 'тест' FROM aggregate_type"
            ),
            {"v": vehicle_id},
        )
        writer.execute(text("SET LOCAL lock_timeout = '2s'"))
        updated = service.update_mileage(writer, writer.get(AppUser, user_id), vehicle_id, 12_345)
        assert updated.mileage == 12_345
        holder.rollback()
