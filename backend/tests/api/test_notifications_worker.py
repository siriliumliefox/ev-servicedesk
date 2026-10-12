"""Worker уведомлений (Глава 15, ADR 0019 п. 2, 6, 7, 9, 13) с фейковым отправителем FCM.

Тесты чек-листа: доставка push < 10 с (от публикации до вызова отправителя через сигнал
Redis — `test_publication_reaches_sender_via_redis_signal_fast`; на устройстве — вручную,
docs/NOTIFICATIONS_E2E.md) и cron-задача на данных с искусственно «просроченными» агрегатами
(`test_reminders_on_overdue_aggregates`).
"""

import time
from datetime import UTC, date, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.time import BUSINESS_TZ
from app.domain.notifications.dispatch import retry_delay
from app.domain.notifications.push import Outcome, PushResult
from app.domain.notifications.reminders import run_maintenance_reminders
from app.domain.tickets.events import MessageCreated, TicketEvents, TicketUpdated
from app.models import (
    MaintenanceReminder,
    Notification,
    NotificationDelivery,
    PushToken,
)
from app.models.enums import UserRole
from tests.api.conftest import API, Headers, model_id
from tests.api.notifications_support import feed, publish


@pytest.fixture
def admin(as_staff) -> Headers:
    return as_staff("+375293490001", UserRole.ADMIN)[0]


def deliveries(db: Session, notification_id: int) -> list[NotificationDelivery]:
    db.expire_all()
    return list(
        db.scalars(
            select(NotificationDelivery)
            .where(NotificationDelivery.notification_id == notification_id)
            .order_by(NotificationDelivery.id)
        )
    )


# ---------- Очередь и повторы (ADR 0019 п. 9) ----------


def test_retry_with_backoff_then_failed(
    client, admin, make_owner, make_worker, sender, settings, db
):
    owner = make_owner(None)
    sender.outcomes[owner.token] = PushResult(Outcome.RETRY, "UNAVAILABLE")
    news = publish(client, admin, type="news", message="Повтор")
    worker = make_worker()

    for attempt in range(1, settings.push_max_attempts + 1):
        before = datetime.now(UTC)
        assert worker.dispatch() == 1
        (row,) = deliveries(db, news["id"])
        assert row.attempts == attempt and row.error_code == "UNAVAILABLE"
        assert row.delivered_at is None
        if attempt < settings.push_max_attempts:
            assert row.failed_at is None
            assert row.next_attempt_at >= before + retry_delay(settings, attempt)
            assert worker.dispatch() == 0, "до срока повтора строка не берётся"
            row.next_attempt_at = datetime.now(UTC) - timedelta(seconds=1)
            db.commit()
    assert row.failed_at is not None
    assert worker.dispatch() == 0
    assert retry_delay(settings, 1) == timedelta(seconds=10)
    assert retry_delay(settings, 4) == timedelta(seconds=640)  # ~10 мин


def test_retry_then_success_clears_error(client, admin, make_owner, make_worker, sender, db):
    owner = make_owner(None)
    sender.outcomes[owner.token] = PushResult(Outcome.RETRY, "QUOTA_EXCEEDED")
    news = publish(client, admin, type="news", message="Со второго раза")
    worker = make_worker()
    worker.dispatch()
    (row,) = deliveries(db, news["id"])
    row.next_attempt_at = datetime.now(UTC) - timedelta(seconds=1)
    db.commit()
    del sender.outcomes[owner.token]
    worker.dispatch()
    (row,) = deliveries(db, news["id"])
    assert (row.attempts, row.error_code, row.failed_at) == (2, None, None)
    assert row.delivered_at is not None


def test_invalid_token_is_revoked_and_its_queue_closed(
    client, admin, make_owner, make_worker, sender, db
):
    owner = make_owner(None)
    sender.outcomes[owner.token] = PushResult(Outcome.INVALID_TOKEN, "UNREGISTERED")
    first = publish(client, admin, type="news", message="1")
    second = publish(client, admin, type="news", message="2")
    make_worker().dispatch()
    (a,) = deliveries(db, first["id"])
    (b,) = deliveries(db, second["id"])
    assert (a.error_code, b.error_code) == ("UNREGISTERED", "TOKEN_REVOKED")
    assert a.failed_at and b.failed_at and b.attempts == 0
    token = db.scalars(select(PushToken).where(PushToken.token == owner.token)).one()
    assert token.revoked_at is not None
    third = publish(client, admin, type="news", message="3")
    assert deliveries(db, third["id"]) == [], "в очередь попадают только активные токены"
    assert feed(client, owner.headers)["items"][0]["id"] == third["id"], "лента — без push"


def test_failed_final_error_without_retry(client, admin, make_owner, make_worker, sender, db):
    owner = make_owner(None)
    sender.outcomes[owner.token] = PushResult(Outcome.FAILED, "PERMISSION_DENIED")
    news = publish(client, admin, type="news", message="Ошибка")
    make_worker().dispatch()
    (row,) = deliveries(db, news["id"])
    assert (row.attempts, row.error_code) == (1, "PERMISSION_DENIED") and row.failed_at


def test_batches_are_drained(client, admin, make_owner, make_worker, sender, settings, db):
    owners = [make_owner(None) for _ in range(3)]
    small = settings.model_copy(update={"notifications_batch_size": 2})
    worker = make_worker()
    worker.settings = small
    publish(client, admin, type="promo", message="Всем")
    assert worker.dispatch() == 3
    assert {m.token for m in sender.sent} == {o.token for o in owners}


# ---------- Доставка < 10 с: публикация → сигнал Redis → отправитель ----------


def test_publication_reaches_sender_via_redis_signal_fast(
    client, admin, make_owner, make_worker, sender
):
    owner = make_owner("Zeekr")
    worker = make_worker()
    worker._pubsub = worker._subscribe()
    assert worker._pubsub is not None
    worker._pubsub.get_message(timeout=1)  # подтверждения подписок
    worker._pubsub.get_message(timeout=1)

    started = time.monotonic()
    publish(client, admin, type="news", message="Быстро")
    worker._wait()
    elapsed = time.monotonic() - started
    assert [m.body for m in sender.to(owner.token)] == ["Быстро"]
    assert elapsed < 10, f"доставка до отправителя за {elapsed:.1f} с"
    worker._close_pubsub()


# ---------- Cron: напоминания о ТО (C-11, N-10, ADR 0019 п. 5–7) ----------


def regulation(client: TestClient, admin: Headers, model: int, code: str, **interval) -> None:
    r = client.post(
        f"{API}/maintenance-regulations",
        json={"vehicle_model_id": model, "aggregate_type_code": code, **interval},
        headers=admin,
    )
    assert r.status_code == 201, r.text


def replace(client: TestClient, admin: Headers, vid: int, code: str, day: date, km: int) -> None:
    r = client.post(
        f"{API}/vehicles/{vid}/aggregate-statuses/{code}/replace",
        json={"replaced_at": str(day), "mileage_at_replacement": km},
        headers=admin,
    )
    assert r.status_code == 200, r.text


def mileage(client: TestClient, headers: Headers, vid: int, km: int) -> None:
    r = client.patch(f"{API}/vehicles/{vid}/mileage", json={"mileage": km}, headers=headers)
    assert r.status_code == 200, r.text


def reminders(db: Session, vid: int) -> list[tuple[str, str]]:
    db.expire_all()
    rows = db.execute(
        select(MaintenanceReminder.kind, Notification.message)
        .join(Notification, Notification.id == MaintenanceReminder.notification_id)
        .where(MaintenanceReminder.vehicle_id == vid)
        .order_by(MaintenanceReminder.id)
    ).all()
    return [(k.value, m) for k, m in rows]


def test_reminders_on_overdue_aggregates(
    client, admin, make_owner, make_worker, sender, real_redis, settings, db: Session
):
    owner = make_owner("Zeekr")
    other = make_owner("Zeekr")
    vid = owner.vehicle_id
    model = model_id(client, admin, "Zeekr")
    regulation(client, admin, model, "engine_oil", interval_km=10_000)
    regulation(client, admin, model, "cabin_filter", interval_months=12)
    regulation(client, admin, model, "air_filter", interval_km=30_000)  # без истории — unknown
    start = date(2026, 1, 10)
    replace(client, admin, vid, "engine_oil", start, 0)
    replace(client, admin, vid, "cabin_filter", start, 0)
    worker = make_worker()
    run = lambda day: run_maintenance_reminders(db, worker.outbox, day)  # noqa: E731

    mileage(client, owner.headers, vid, 8_500)  # осталось 1500 км > 1000
    assert run(date(2026, 6, 1)) == 0

    mileage(client, owner.headers, vid, 9_200)  # осталось 800 км ≤ 1000
    assert run(date(2026, 6, 2)) == 1
    assert run(date(2026, 6, 3)) == 0, "повтор в цикле не создаётся"
    assert reminders(db, vid) == [
        ("due_soon", "Zeekr 001 — Масло двигателя: до замены осталось 800 км. Запишитесь на ТО.")
    ]

    # Салонный фильтр: за 7 дней до годовой замены (≤ 14 дней).
    assert run(date(2027, 1, 3)) == 1
    assert reminders(db, vid)[-1] == (
        "due_soon",
        "Zeekr 001 — Салонный фильтр: до замены осталось 7 дн. Запишитесь на ТО.",
    )

    mileage(client, owner.headers, vid, 10_500)  # 105% — красный
    assert run(date(2026, 6, 4)) == 1
    assert reminders(db, vid)[-1] == (
        "overdue",
        "Zeekr 001 — Масло двигателя: срок замены прошёл. Запишитесь на ТО.",
    )
    assert run(date(2026, 6, 5)) == 0

    # Новая замена — новый цикл.
    replace(client, admin, vid, "engine_oil", date(2026, 6, 6), 10_500)
    assert run(date(2026, 6, 7)) == 0
    mileage(client, owner.headers, vid, 20_000)  # осталось 500 км
    assert run(date(2026, 6, 8)) == 1
    assert [k for k, _ in reminders(db, vid)] == ["due_soon", "due_soon", "overdue", "due_soon"]

    # Чужое авто без истории замен — ничего; уведомление — только владельцу, с авто и агрегатом.
    assert reminders(db, other.vehicle_id) == []
    items = feed(client, owner.headers)["items"]
    assert {i["type"] for i in items} == {"maintenance"}
    assert all(i["vehicle_id"] == vid and i["aggregate_type_id"] for i in items)
    assert feed(client, other.headers)["items"] == []

    worker.dispatch()
    pushes = sender.to(owner.token)
    assert len(pushes) == 4 and {p.title for p in pushes} == {"Пора на ТО"}
    assert pushes[0].data["vehicle_id"] == str(vid)
    assert "VIN" not in pushes[0].body and owner.headers  # текст без ПД

    # Напоминания — не публикации: в ленту админа не попадают.
    r = client.get(f"{API}/notifications/published", headers=admin)
    assert r.json()["items"] == []


def test_red_first_gives_only_overdue_and_no_late_due_soon(
    client, admin, make_owner, make_worker, db: Session
):
    owner = make_owner("Zeekr")
    vid = owner.vehicle_id
    model = model_id(client, admin, "Zeekr")
    regulation(client, admin, model, "engine_oil", interval_km=10_000)
    replace(client, admin, vid, "engine_oil", date(2026, 1, 10), 0)
    mileage(client, owner.headers, vid, 12_000)
    worker = make_worker()
    assert run_maintenance_reminders(db, worker.outbox, date(2026, 6, 1)) == 1
    # Регламент увеличили — агрегат снова «скоро», но в этом цикле напоминание уже было.
    regulation(client, admin, model, "engine_oil", interval_km=12_500)
    assert run_maintenance_reminders(db, worker.outbox, date(2026, 6, 2)) == 0
    assert [k for k, _ in reminders(db, vid)] == ["overdue"]


def test_reminders_skip_deleted_vehicles_and_withdrawn_clients(
    client, admin, make_owner, make_worker, db: Session
):
    gone = make_owner("Zeekr")
    withdrawn = make_owner("Zeekr")
    model = model_id(client, admin, "Zeekr")
    regulation(client, admin, model, "engine_oil", interval_km=10_000)
    for o in (gone, withdrawn):
        replace(client, admin, o.vehicle_id, "engine_oil", date(2026, 1, 10), 0)
        mileage(client, o.headers, o.vehicle_id, 12_000)
    assert (
        client.delete(f"{API}/vehicles/{gone.vehicle_id}", headers=gone.headers).status_code == 204
    )
    assert client.delete(f"{API}/auth/pd-consent", headers=withdrawn.headers).status_code == 202
    assert run_maintenance_reminders(db, make_worker().outbox, date(2026, 6, 1)) == 0


def test_worker_runs_reminders_once_a_day_from_configured_hour(make_worker, settings):
    clock = [datetime(2026, 6, 1, settings.maintenance_reminder_hour - 1, 59, tzinfo=BUSINESS_TZ)]
    worker = make_worker(now=lambda: clock[0])
    assert not worker.reminders_due()
    clock[0] = clock[0].replace(hour=settings.maintenance_reminder_hour, minute=0)
    assert worker.reminders_due()
    worker.tick()
    assert worker.reminders_done_on == date(2026, 6, 1) and not worker.reminders_due()
    clock[0] = clock[0] + timedelta(days=1)
    assert worker.reminders_due()


# ---------- Push по тикетам (ADR 0019 п. 13) ----------


def test_ticket_push_for_staff_messages_and_status_changes(
    client, make_owner, make_worker, make_ticket, as_staff, sender, real_redis, settings, db
):
    owner = make_owner("Zeekr")
    eng_headers, eng = as_staff("+375293490002")
    ticket = make_ticket(owner.vehicle_id, eng)
    events = TicketEvents(real_redis, settings.redis_channel_prefix)
    worker = make_worker()
    worker._pubsub = worker._subscribe()
    worker._pubsub.get_message(timeout=1)
    worker._pubsub.get_message(timeout=1)

    r = client.post(
        f"{API}/tickets/{ticket.id}/messages",
        json={"body": "Перезагрузите ГУ"},
        headers=eng_headers,
    )
    assert r.status_code == 201, r.text
    worker._wait()  # событие Tickets из Redis → push
    assert [(m.title, m.body) for m in sender.to(owner.token)] == [
        ("Поддержка", f"Новое сообщение по обращению №{ticket.id}")
    ]
    assert "Перезагрузите" not in sender.to(owner.token)[0].body, "текст сообщения не уходит"
    assert sender.to(owner.token)[0].data == {"type": "ticket", "ticket_id": str(ticket.id)}
    worker._close_pubsub()

    # Повтор того же события (вторая реплика) — без push.
    message_id = r.json()["id"]
    event = MessageCreated(ticket_id=ticket.id, message_id=message_id)
    worker.handle_message(events.channel(ticket.id), event.model_dump_json())
    assert len(sender.to(owner.token)) == 1

    # Сообщение клиента push не вызывает.
    r = client.post(
        f"{API}/tickets/{ticket.id}/messages", json={"body": "Не помогло"}, headers=owner.headers
    )
    mine = MessageCreated(ticket_id=ticket.id, message_id=r.json()["id"])
    worker.handle_message(events.channel(ticket.id), mine.model_dump_json())
    assert len(sender.to(owner.token)) == 1

    # Смена статуса — один push на новый статус.
    updated = TicketUpdated(ticket_id=ticket.id).model_dump_json()
    worker.handle_message(events.channel(ticket.id), updated)
    assert sender.to(owner.token)[-1].body == f"Статус обращения №{ticket.id}: в работе"
    worker.handle_message(events.channel(ticket.id), updated)
    assert len(sender.to(owner.token)) == 2, "статус не менялся — push нет"
    r = client.patch(
        f"{API}/tickets/{ticket.id}/status", json={"status": "resolved"}, headers=eng_headers
    )
    assert r.status_code == 200, r.text
    worker.handle_message(events.channel(ticket.id), updated)
    assert sender.to(owner.token)[-1].body == f"Статус обращения №{ticket.id}: решено"

    # Чужие и повреждённые события пропускаются.
    worker.handle_message(events.channel(10**12), TicketUpdated(ticket_id=10**12).model_dump_json())
    worker.handle_message(events.channel(ticket.id), "{not json")
    assert len(sender.to(owner.token)) == 3
    assert db.scalar(select(func.count()).select_from(Notification)) == 0, "в ленту не пишется"


def test_ticket_push_skips_new_ticket_and_unavailable_client(
    client, make_owner, make_worker, make_ticket, as_staff, sender, real_redis, settings
):
    owner = make_owner("Zeekr")
    events = TicketEvents(real_redis, settings.redis_channel_prefix)
    worker = make_worker()
    fresh = make_ticket(owner.vehicle_id)  # «Новый», без инженера
    worker.handle_message(
        events.channel(fresh.id), TicketUpdated(ticket_id=fresh.id).model_dump_json()
    )
    assert sender.sent == [], "первое событие «Нового» тикета — не смена статуса"

    taken = make_ticket(owner.vehicle_id, as_staff("+375293490003")[1])
    assert client.delete(f"{API}/auth/pd-consent", headers=owner.headers).status_code == 202
    worker.handle_message(
        events.channel(taken.id), TicketUpdated(ticket_id=taken.id).model_dump_json()
    )
    assert sender.sent == [], "клиент отозвал согласие — push нет"
