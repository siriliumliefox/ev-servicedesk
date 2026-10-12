"""Analytics Service (Глава 16, ADR 0020): сверка с ручным расчётом, витрина, доступ, период."""

from collections.abc import Callable
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.domain.analytics.refresh import refresh_views
from app.models import (
    AnalyticsRefresh,
    Notification,
    NotificationDelivery,
    NotificationRecipient,
    PushToken,
    Ticket,
)
from app.models.enums import UserRole
from tests.api.conftest import API, Headers, assert_contract
from tests.support import analytics_control as control

OPERATIONS = {
    "/analytics/ticket-resolution": "getTicketResolutionStats",
    "/analytics/problem-models": "listProblemModels",
    "/analytics/maintenance-conversion": "getMaintenanceConversionStats",
}
MARCH = control.MARCH


@pytest.fixture
def admin(as_staff: Callable[..., tuple[Headers, object]]) -> Headers:
    return as_staff("+375290160001", UserRole.ADMIN)[0]


@pytest.fixture
def world(db: Session) -> control.World:
    loaded = control.load(db)
    assert refresh_views(db)
    return loaded


def get(client: TestClient, headers: Headers, path: str, **params) -> dict:
    r = client.get(f"{API}{path}", params=params, headers=headers)
    assert r.status_code == 200, r.text
    assert_contract(r, OPERATIONS[path])
    return r.json()


def test_control_dataset_matches_manual_calculation(
    client: TestClient, admin: Headers, world: control.World
) -> None:
    """Все запросы контроля (docs/ANALYTICS_CONTROL.md) — по контракту и как в ручном расчёте."""
    model_ids = {name: model.id for name, model in world.models.items()}

    def fetch(path: str, params: dict) -> dict:
        return get(client, admin, path.removeprefix(API), **params)

    assert control.verify(fetch, model_ids) == 0


def test_data_after_refresh_is_visible_only_after_next_refresh(
    client: TestClient, admin: Headers, world: control.World, db: Session
) -> None:
    before = get(client, admin, "/analytics/ticket-resolution", **MARCH)
    t = world.tickets["T5"]
    db.add(
        Ticket(
            vehicle_id=t.vehicle_id,
            category=t.category,
            description="Новый тикет после обновления витрины",
            created_at=t.created_at,
            sla_due_at=t.sla_due_at,
        )
    )
    db.commit()

    stale = get(client, admin, "/analytics/ticket-resolution", **MARCH)
    assert stale["tickets_created"] == before["tickets_created"] == 8
    assert stale["computed_at"] == before["computed_at"]

    assert refresh_views(db)
    fresh = get(client, admin, "/analytics/ticket-resolution", **MARCH)
    assert fresh["tickets_created"] == 9
    assert fresh["computed_at"] > before["computed_at"]


def test_computed_at_is_the_oldest_refresh_of_used_views(
    client: TestClient, admin: Headers, world: control.World, db: Session
) -> None:
    old = datetime(2026, 1, 1, tzinfo=UTC)
    db.execute(
        text("UPDATE analytics_refresh SET refreshed_at = :at WHERE view_name = :v"),
        {"at": old, "v": "analytics_reminder_fact"},
    )
    db.commit()
    conversion = get(client, admin, "/analytics/maintenance-conversion", **MARCH)
    resolution = get(client, admin, "/analytics/ticket-resolution", **MARCH)
    assert datetime.fromisoformat(conversion["computed_at"]) == old
    assert datetime.fromisoformat(resolution["computed_at"]) > old


def test_refresh_records_time_before_recalculation(db: Session) -> None:
    started = db.execute(text("SELECT clock_timestamp()")).scalar_one()
    assert refresh_views(db)
    times = db.execute(select(AnalyticsRefresh.view_name, AnalyticsRefresh.refreshed_at)).all()
    assert {name for name, _ in times} == {
        "analytics_ticket_fact",
        "analytics_reminder_fact",
        "analytics_vehicle_model_fact",
    }
    assert all(at >= started for _, at in times)


# --- доступ -----------------------------------------------------------------------------------


@pytest.mark.parametrize("path", OPERATIONS)
def test_requires_token(client: TestClient, path: str) -> None:
    r = client.get(f"{API}{path}", params=MARCH)
    assert r.status_code == 401
    assert_contract(r, OPERATIONS[path])


@pytest.mark.parametrize("path", OPERATIONS)
@pytest.mark.parametrize("role", ["client", "engineer"])
def test_only_admin(
    client: TestClient,
    as_client: Callable[[str], Headers],
    as_staff: Callable[..., tuple[Headers, object]],
    path: str,
    role: str,
) -> None:
    headers = (
        as_client("+375290160002")
        if role == "client"
        else as_staff("+375290160003", UserRole.ENGINEER)[0]
    )
    r = client.get(f"{API}{path}", params=MARCH, headers=headers)
    assert r.status_code == 403
    assert_contract(r, OPERATIONS[path])


# --- период и параметры -----------------------------------------------------------------------


@pytest.mark.parametrize("path", OPERATIONS)
@pytest.mark.parametrize(
    ("params", "code"),
    [
        ({"date_from": "2026-03-02", "date_to": "2026-03-01"}, "INVALID_PERIOD"),
        ({"date_from": "2025-01-01", "date_to": "2026-01-02"}, "PERIOD_TOO_LONG"),  # 367 дней
        ({"date_from": "2026-03-01"}, "VALIDATION_ERROR"),
        ({"date_from": "2026-03-01", "date_to": "31.03.2026"}, "VALIDATION_ERROR"),
    ],
)
def test_invalid_period(
    client: TestClient, admin: Headers, path: str, params: dict, code: str
) -> None:
    r = client.get(f"{API}{path}", params=params, headers=admin)
    assert r.status_code == 422, r.text
    assert r.json()["error"]["code"] == code
    assert_contract(r, OPERATIONS[path])


@pytest.mark.parametrize("path", OPERATIONS)
def test_period_of_366_days_and_single_day(client: TestClient, admin: Headers, path: str) -> None:
    get(client, admin, path, date_from="2024-01-01", date_to="2024-12-31")  # високосный — 366
    get(client, admin, path, date_from="2026-03-01", date_to="2026-03-01")


@pytest.mark.parametrize(
    ("path", "params"),
    [
        ("/analytics/ticket-resolution", {"category": "brakes"}),
        ("/analytics/ticket-resolution", {"vehicle_model_id": "x"}),
        ("/analytics/maintenance-conversion", {"vehicle_model_id": 2**63}),
        ("/analytics/problem-models", {"page_size": 101}),
    ],
)
def test_invalid_filters(client: TestClient, admin: Headers, path: str, params: dict) -> None:
    r = client.get(f"{API}{path}", params=MARCH | params, headers=admin)
    assert r.status_code == 422, r.text
    assert_contract(r, OPERATIONS[path])


def test_empty_period_and_unknown_model(client: TestClient, admin: Headers) -> None:
    """Пустая выборка — нули и null, неизвестная модель — тоже пустая выборка, а не 404."""
    period = {"date_from": "2020-01-01", "date_to": "2020-01-31"}
    resolution = get(client, admin, "/analytics/ticket-resolution", **period)
    assert resolution["tickets_created"] == 0
    assert resolution["avg_resolution_hours"] is None
    assert resolution["median_resolution_hours"] is None
    models = get(client, admin, "/analytics/problem-models", **period)
    assert models["items"] == []
    assert models["meta"]["total_items"] == 0
    conversion = get(
        client, admin, "/analytics/maintenance-conversion", vehicle_model_id=999_999, **period
    )
    assert conversion["ticket_to_maintenance_rate"] is None
    assert conversion["notification_to_maintenance_rate"] is None


def test_future_date_to_is_allowed(client: TestClient, admin: Headers) -> None:
    today = datetime.now(UTC).date()
    get(
        client,
        admin,
        "/analytics/ticket-resolution",
        date_from=today.isoformat(),
        date_to=(today + timedelta(days=30)).isoformat(),
    )


def test_opening_counts_per_recipient(
    client: TestClient, admin: Headers, world: control.World, db: Session
) -> None:
    """Получение — пара «напоминание, получатель»: открытие на устройстве другого получателя
    того же напоминания не делает получение открытым (ADR 0020 п. 8)."""
    reminder = db.scalars(
        select(Notification).where(Notification.message == "Контрольное напоминание R2")
    ).one()
    other = world.vehicles["V4"].user_id  # клиент без устройств в наборе
    token = PushToken(user_id=other, token="control-token-other")
    db.add_all([token, NotificationRecipient(notification_id=reminder.id, user_id=other)])
    db.flush()
    db.add(
        NotificationDelivery(
            notification_id=reminder.id,
            push_token_id=token.id,
            delivered_at=reminder.created_at,
            opened_at=reminder.created_at,
        )
    )
    db.commit()
    assert refresh_views(db)
    body = get(client, admin, "/analytics/maintenance-conversion", **MARCH)
    # Было 5 получений, 3 открытых; R2 у C2 по-прежнему не открыто, у второго получателя — да.
    assert (body["notifications_recipients"], body["notifications_opened"]) == (6, 4)
