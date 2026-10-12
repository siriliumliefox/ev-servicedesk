"""Производительность дашборда (Глава 16, ADR 0020 п. 10): эмулированный объём данных.

10 000 тикетов за 2 года, 20 моделей, 5 000 авто, 20 000 получений напоминаний о ТО,
30 000 доставок push, 8 000 работ ТО — генерация SQL (generate_series) в транзакции теста.
Порог: каждая операция за 366 дней, с фильтрами и без, — p95 из 20 вызовов < 300 мс;
полное обновление витрины < 5 с.
"""

import time
from collections.abc import Callable

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.domain.analytics.refresh import refresh_views
from app.models.enums import UserRole
from tests.api.conftest import API, Headers

CALLS = 20
P95_LIMIT_SECONDS = 0.3
REFRESH_LIMIT_SECONDS = 5.0
PERIOD = {"date_from": "2025-06-01", "date_to": "2026-06-01"}  # 366 дней

VOLUME_SQL = [
    # 20 моделей, 5 000 клиентов с авто (каждое 25-е удалено), по 2 устройства у клиента.
    """INSERT INTO vehicle_model (brand, model)
       SELECT 'Perf', 'M' || i FROM generate_series(1, 20) i""",
    """INSERT INTO app_user (phone, role)
       SELECT '+37501' || lpad(i::text, 7, '0'), 'client' FROM generate_series(1, 5000) i""",
    """INSERT INTO vehicle (user_id, vehicle_model_id, vin, mileage, deleted_at)
       SELECT u.id, m.id, 'PERF' || lpad(u.n::text, 13, '0'), 10000,
              CASE WHEN u.n % 25 = 0 THEN now() END
       FROM (SELECT id, row_number() OVER (ORDER BY id) n FROM app_user
             WHERE phone LIKE '+37501%') u
       JOIN (SELECT id, row_number() OVER (ORDER BY id) - 1 k FROM vehicle_model
             WHERE brand = 'Perf') m ON m.k = u.n % 20""",
    """INSERT INTO push_token (user_id, token)
       SELECT u.id, 'perf-' || u.id || '-' || k
       FROM app_user u, generate_series(1, 2) k WHERE u.phone LIKE '+37501%'""",
    # 10 000 тикетов каждые 105 минут с 2025-01-01: 70% решены, у 90% — первичный ответ.
    """INSERT INTO ticket (vehicle_id, category, status, description, created_at, sla_due_at,
                           first_response_at, resolved_at)
       SELECT v.id,
              (ARRAY['navigation','audio','sim','app_crash','maintenance'])[i % 5 + 1]
                  ::ticket_category,
              CASE WHEN i % 10 < 7 THEN 'resolved' ELSE 'in_progress' END::ticket_status,
              'perf', c, c + interval '8 hours',
              CASE WHEN i % 10 < 9 THEN c + (i % 7 + 1) * interval '17 minutes' END,
              CASE WHEN i % 10 < 7 THEN c + (i % 50 + 1) * interval '1 hour' END
       FROM generate_series(1, 10000) i
       CROSS JOIN LATERAL (SELECT timestamptz '2025-01-01 00:00+03'
                                  + i * interval '105 minutes' AS c) t
       JOIN (SELECT id, row_number() OVER (ORDER BY id) - 1 k FROM vehicle
             WHERE vin LIKE 'PERF%') v ON v.k = i % 5000""",
    # 8 000 работ ТО: половина — по тикетам, половина записана администратором.
    """INSERT INTO maintenance_record (vehicle_id, ticket_id, performed_at, mileage_at_service,
                                       description)
       SELECT vehicle_id, CASE WHEN n <= 4000 THEN id END, created_at::date + 1, 10000, 'perf'
       FROM (SELECT id, vehicle_id, created_at, row_number() OVER (ORDER BY id) n
             FROM ticket WHERE description = 'perf') t
       WHERE n <= 8000""",
    # 20 000 напоминаний о ТО (по одному получателю) каждые 52 минуты.
    """WITH n AS (
         INSERT INTO notification (type, vehicle_id, aggregate_type_id, message, created_at)
         SELECT 'maintenance', v.id, (SELECT id FROM aggregate_type WHERE code = 'engine_oil'),
                'perf', timestamptz '2025-01-01 10:00+03' + i * interval '52 minutes'
         FROM generate_series(1, 20000) i
         JOIN (SELECT id, row_number() OVER (ORDER BY id) - 1 k FROM vehicle
               WHERE vin LIKE 'PERF%') v ON v.k = i % 5000
         RETURNING id, vehicle_id)
       INSERT INTO notification_recipient (notification_id, user_id)
       SELECT n.id, v.user_id FROM n JOIN vehicle v ON v.id = n.vehicle_id""",
    # 30 000 доставок: на первое устройство — всегда, на второе — у половины; треть открыта.
    """INSERT INTO notification_delivery (notification_id, push_token_id, delivered_at,
                                          opened_at)
       SELECT r.notification_id, p.id, r.created_at,
              CASE WHEN (r.notification_id + p.id) % 3 = 0 THEN r.created_at END
       FROM notification_recipient r
       JOIN notification n ON n.id = r.notification_id AND n.message = 'perf'
       JOIN push_token p ON p.user_id = r.user_id
       WHERE p.token LIKE '%-1' OR r.notification_id % 2 = 0""",
]


@pytest.fixture
def volume(db: Session) -> dict[str, int]:
    for sql in VOLUME_SQL:
        db.execute(text(sql))
    db.commit()
    counts = {
        table: db.execute(text(f"SELECT count(*) FROM {table}")).scalar_one()
        for table in (
            "ticket",
            "vehicle",
            "notification_recipient",
            "notification_delivery",
            "maintenance_record",
        )
    }
    db.execute(text("ANALYZE"))
    return counts


def p95(timings: list[float]) -> float:
    return sorted(timings)[int(len(timings) * 0.95) - 1]


def test_dashboard_on_emulated_volume(
    client: TestClient,
    db: Session,
    as_staff: Callable[..., tuple[Headers, object]],
    volume: dict[str, int],
) -> None:
    assert volume == {
        "ticket": 10_000,
        "vehicle": 5_000,
        "notification_recipient": 20_000,
        "notification_delivery": 30_000,
        "maintenance_record": 8_000,
    }
    started = time.perf_counter()
    assert refresh_views(db)
    refresh_seconds = time.perf_counter() - started
    assert refresh_seconds < REFRESH_LIMIT_SECONDS, f"обновление витрины {refresh_seconds:.2f} с"

    admin, _ = as_staff("+375290160099", UserRole.ADMIN)
    model_id = db.execute(
        text("SELECT id FROM vehicle_model WHERE brand = 'Perf' ORDER BY id LIMIT 1")
    ).scalar_one()
    requests = {
        "ticket-resolution": PERIOD,
        "ticket-resolution?filters": PERIOD
        | {"vehicle_model_id": model_id, "category": "navigation"},
        "problem-models": PERIOD,
        "problem-models?page": PERIOD | {"page": 2, "page_size": 5},
        "maintenance-conversion": PERIOD,
        "maintenance-conversion?filters": PERIOD | {"vehicle_model_id": model_id},
    }
    report = {}
    for name, params in requests.items():
        path = f"{API}/analytics/{name.split('?')[0]}"
        timings = []
        for _ in range(CALLS):
            started = time.perf_counter()
            r = client.get(path, params=params, headers=admin)
            timings.append(time.perf_counter() - started)
            assert r.status_code == 200, r.text
        report[name] = p95(timings)
    slow = {name: f"{t * 1000:.0f} мс" for name, t in report.items() if t >= P95_LIMIT_SECONDS}
    assert not slow, f"p95 ≥ {P95_LIMIT_SECONDS * 1000:.0f} мс: {slow}"

    body = client.get(f"{API}/analytics/ticket-resolution", params=PERIOD, headers=admin).json()
    assert body["tickets_created"] > 4_000  # период действительно покрывает объём
    print(
        f"\nобновление витрины: {refresh_seconds * 1000:.0f} мс; p95: "
        + ", ".join(f"{n} {t * 1000:.0f} мс" for n, t in report.items())
    )
