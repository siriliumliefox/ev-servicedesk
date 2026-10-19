"""Аудит целостности `app.tools.integrity` (Глава 17, ADR 0021 п. 4, 8).

Мир собирается через API всех модулей — с блокировкой, отзывом согласия и удалением авто, —
и аудит не находит нарушений. Затем каждое правило ломается прямым SQL (мимо API), и его
проверка должна это заметить: у каждой проверки — своя мутация.
"""

from collections.abc import Callable
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.domain.notifications.reminders import run_maintenance_reminders
from app.models.enums import UserRole
from app.tools import integrity
from tests.api.conftest import API, Headers, model_id
from tests.api.notifications_support import publish, regulation
from tests.api.ticket_support import create
from tests.api.vehicle_support import replace, set_mileage


@dataclass
class World:
    a_ticket: int
    b_ticket: int
    a_vehicle: int
    a_user: int
    b_user: int
    engineer: int
    reminder_notification: int


def user_id(client, headers: Headers) -> int:
    return client.get(f"{API}/me", headers=headers).json()["id"]


@pytest.fixture
def world(client, as_staff, make_owner, make_worker, db: Session) -> World:
    admin, _ = as_staff("+375296800001", UserRole.ADMIN)
    eng_headers, eng = as_staff("+375296800002")
    a = make_owner("Zeekr")
    b = make_owner("Zeekr")
    gone = make_owner("Zeekr")
    withdrawn = make_owner(None)

    # Aggregates → Notifications: напоминание о ТО, доставка.
    model = model_id(client, admin, "Zeekr")
    regulation(client, admin, model, "engine_oil", interval_km=10_000)
    replace(client, admin, a.vehicle_id, "engine_oil", date(2026, 1, 10), 0)
    set_mileage(client, a.headers, a.vehicle_id, 9_500)
    worker = make_worker()
    assert run_maintenance_reminders(db, worker.outbox, date(2026, 6, 1)) == 1
    publish(client, admin, type="news", message="Новость для всех")
    worker.dispatch()

    # Tickets ↔ Vehicle/Aggregates: тикет, переписка, замена по тикету.
    a_ticket = create(client, a.headers, a.vehicle_id, category="maintenance", description="ТО")
    tid = a_ticket["id"]
    assert client.post(f"{API}/tickets/{tid}/claim", headers=eng_headers).status_code == 200
    for headers in (eng_headers, a.headers):
        r = client.post(f"{API}/tickets/{tid}/messages", json={"body": "ок"}, headers=headers)
        assert r.status_code == 201
    r = client.post(
        f"{API}/vehicles/{a.vehicle_id}/aggregate-statuses/engine_oil/replace",
        json={"replaced_at": "2026-06-02", "mileage_at_replacement": 9_500},
        headers=eng_headers,
    )
    assert r.status_code == 200, r.text
    b_ticket = create(client, b.headers, b.vehicle_id, category="sim", description="Нет сети")

    # Жизненный цикл: удаление авто с тикетом, отзыв согласия, блокировка.
    create(client, gone.headers, gone.vehicle_id, category="sim", description="Связь")
    r = client.delete(f"{API}/vehicles/{gone.vehicle_id}", headers=gone.headers)
    assert r.status_code == 204
    assert client.delete(f"{API}/auth/pd-consent", headers=withdrawn.headers).status_code == 202
    blocked = user_id(client, b.headers)
    r = client.patch(f"{API}/users/{blocked}", json={"is_active": False}, headers=admin)
    assert r.status_code == 200
    worker.dispatch()

    (reminder_notification,) = db.execute(
        text("SELECT notification_id FROM maintenance_reminder WHERE vehicle_id = :v"),
        {"v": a.vehicle_id},
    ).scalars()
    return World(
        a_ticket=tid,
        b_ticket=b_ticket["id"],
        a_vehicle=a.vehicle_id,
        a_user=user_id(client, a.headers),
        b_user=blocked,
        engineer=eng.id,
        reminder_notification=reminder_notification,
    )


def test_consistent_world_has_no_violations(world, db: Session):
    assert integrity.run_checks(db) == []


def sql(db: Session, statement: str, **params) -> None:
    db.execute(text(statement), params)


MUTATIONS: dict[str, Callable[[Session, World], None]] = {
    "replacement_without_history": lambda db, w: sql(
        db,
        "UPDATE vehicle_aggregate_status SET last_replaced_mileage = last_replaced_mileage + 1"
        " WHERE vehicle_id = :v",
        v=w.a_vehicle,
    ),
    "maintenance_record_of_other_vehicle_ticket": lambda db, w: sql(
        db,
        "UPDATE maintenance_record SET ticket_id = :t WHERE vehicle_id = :v",
        t=w.b_ticket,
        v=w.a_vehicle,
    ),
    "maintenance_record_by_client": lambda db, w: sql(
        db,
        "UPDATE maintenance_record SET performed_by_user_id = :u WHERE vehicle_id = :v",
        u=w.a_user,
        v=w.a_vehicle,
    ),
    "vehicle_owner_not_client": lambda db, w: sql(
        db, "UPDATE app_user SET role = 'engineer', password_hash = 'x' WHERE id = :u", u=w.a_user
    ),
    "ticket_assignee_is_client": lambda db, w: sql(
        db, "UPDATE ticket SET assigned_engineer_id = :u WHERE id = :t", u=w.a_user, t=w.a_ticket
    ),
    "ticket_created_for_deleted_vehicle": lambda db, w: sql(
        db,
        "UPDATE vehicle SET deleted_at = (SELECT created_at FROM ticket WHERE id = :t)"
        " - interval '1 minute' WHERE id = :v",
        t=w.a_ticket,
        v=w.a_vehicle,
    ),
    "client_message_in_foreign_ticket": lambda db, w: sql(
        db,
        "INSERT INTO ticket_message (ticket_id, author_id, body) VALUES (:t, :u, 'чужой')",
        t=w.a_ticket,
        u=w.b_user,
    ),
    "active_refresh_token_of_unavailable_user": lambda db, w: sql(
        db, "UPDATE app_user SET is_active = false WHERE id = :u", u=w.a_user
    ),
    "active_push_token_of_ineligible_user": lambda db, w: sql(
        db, "UPDATE pd_consent SET withdrawn_at = now() WHERE user_id = :u", u=w.a_user
    ),
    "notification_recipient_not_client": lambda db, w: sql(
        db,
        "INSERT INTO notification_recipient (notification_id, user_id) VALUES (:n, :u)",
        n=w.reminder_notification,
        u=w.engineer,
    ),
    "vehicle_notification_to_non_owner": lambda db, w: sql(
        db,
        "INSERT INTO notification_recipient (notification_id, user_id) VALUES (:n, :u)",
        n=w.reminder_notification,
        u=w.b_user,
    ),
    "reminder_notification_mismatch": lambda db, w: sql(
        db,
        "UPDATE notification SET aggregate_type_id ="
        " (SELECT id FROM aggregate_type WHERE code = 'cabin_filter') WHERE id = :n",
        n=w.reminder_notification,
    ),
    "reminder_for_deleted_vehicle": lambda db, w: sql(
        db,
        "UPDATE vehicle SET deleted_at = (SELECT created_at FROM maintenance_reminder"
        " WHERE vehicle_id = :v) - interval '1 minute' WHERE id = :v",
        v=w.a_vehicle,
    ),
    "delivery_to_non_recipient": lambda db, w: sql(
        db,
        "DELETE FROM notification_recipient WHERE notification_id = :n",
        n=w.reminder_notification,
    ),
}


def test_every_check_has_a_mutation():
    assert set(MUTATIONS) == {c.name for c in integrity.CHECKS}


@pytest.mark.parametrize("name", sorted(MUTATIONS))
def test_check_detects_violation(name, world, db: Session):
    MUTATIONS[name](db, world)
    found = {v.check.name: v for v in integrity.run_checks(db)}
    assert name in found, f"проверка {name} не заметила нарушение"


def test_main_prints_names_and_exit_code(world, db: Session, monkeypatch, capsys):
    @contextmanager
    def scope():
        yield db

    monkeypatch.setattr(integrity, "get_session_scope", lambda: scope)
    assert integrity.main() == 0
    out = capsys.readouterr().out
    assert out.count("PASS  ") == len(integrity.CHECKS)

    MUTATIONS["ticket_assignee_is_client"](db, world)
    assert integrity.main() == 1
    out = capsys.readouterr().out
    assert (
        f"FAIL  ticket_assignee_is_client: 1 — Исполнитель тикета — клиент (id: {world.a_ticket})"
        in out
    )
    assert "+3752" not in out, "отчёт без телефонов (ПД)"
