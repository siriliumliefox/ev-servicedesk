"""Worker уведомлений (Глава 15, ADR 0019 п. 2, 6, 7, 9, 13) с фейковым отправителем FCM.

Тесты чек-листа: доставка push < 10 с (от публикации до вызова отправителя через сигнал
Redis — `test_publication_reaches_sender_via_redis_signal_fast`; на устройстве — вручную,
docs/NOTIFICATIONS_E2E.md) и cron-задача на данных с искусственно «просроченными» агрегатами
(`test_reminders_on_overdue_aggregates`).
"""

import time
from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.core.time import BUSINESS_TZ
from app.domain.notifications.dispatch import retry_delay
from app.domain.notifications.push import Outcome, PushResult
from app.domain.notifications.reminders import run_maintenance_reminders
from app.domain.tickets.events import MessageCreated, TicketEvents, TicketUpdated
from app.models import (
    AppUser,
    MaintenanceReminder,
    Notification,
    NotificationDelivery,
    PdConsent,
    PushToken,
)
from app.models.enums import UserRole
from tests.api.conftest import API, Headers, model_id
from tests.api.notifications_support import feed, mileage, publish, regulation, replace


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
        "Zeekr 001 — Масло двигателя: требуется замена. Запишитесь на ТО.",
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


# ---------- Регрессия по независимому ревью (ADR 0019, уточнения) ----------


class FlakySender:
    """Отправитель, падающий на заданном вызове; запоминает все вызовы."""

    def __init__(self, fail_on: int) -> None:
        self.fail_on = fail_on
        self.calls: list[str] = []

    def send(self, message):
        self.calls.append(message.token)
        if len(self.calls) == self.fail_on:
            raise RuntimeError("сбой посреди пачки")
        return PushResult(Outcome.SENT)


def test_crash_mid_batch_does_not_resend_delivered(
    client, admin, make_owner, make_worker, settings, db
):
    a, b = make_owner(None), make_owner(None)
    news = publish(client, admin, type="news", message="Один раз")
    worker = make_worker()
    worker.sender = FlakySender(fail_on=2)
    assert worker.dispatch() == 2
    by_code = sorted(
        (r.error_code or "", r.delivered_at is not None) for r in deliveries(db, news["id"])
    )
    assert by_code == [("", True), ("SENDER_ERROR", False)]
    for row in deliveries(db, news["id"]):
        row.next_attempt_at = datetime.now(UTC) - timedelta(seconds=1)
    db.commit()
    worker.dispatch()
    calls = worker.sender.calls
    assert sorted(calls) == sorted(
        [a.token, b.token, calls[1]]
    ), "доставленный не отправлен повторно"
    assert all(r.delivered_at for r in deliveries(db, news["id"]))


def test_stop_mid_batch_leaves_rest_leased_not_sent(
    client, admin, make_owner, make_worker, sender, settings, db
):
    make_owner(None), make_owner(None)
    news = publish(client, admin, type="news", message="Стоп")
    worker = make_worker()
    original = sender.send

    def send_then_stop(message):
        worker.stop()
        return original(message)

    sender.send = send_then_stop
    worker.dispatch()
    rows = deliveries(db, news["id"])
    assert len(sender.sent) == 1
    pending = [r for r in rows if r.delivered_at is None]
    assert len(pending) == 1 and pending[0].attempts == 0 and pending[0].failed_at is None
    assert pending[0].next_attempt_at > datetime.now(UTC), "строка арендована до истечения срока"


def test_signal_handling_error_does_not_stop_worker(make_worker, monkeypatch):
    worker = make_worker()

    class OneMessage:
        def get_message(self, timeout):
            worker.stop()
            return {"channel": "x", "data": "y"}

        def close(self):
            pass

    def boom(channel, data):
        raise RuntimeError("БД недоступна")

    worker._pubsub = OneMessage()
    monkeypatch.setattr(worker, "handle_message", boom)
    worker._wait()  # исключение залогировано, а не проброшено


def test_failed_reminders_retry_after_pause(make_worker, settings):
    clock = [datetime(2026, 6, 1, settings.maintenance_reminder_hour, 0, tzinfo=BUSINESS_TZ)]
    worker = make_worker(now=lambda: clock[0])

    def broken_scope():
        raise RuntimeError("БД недоступна")

    worker.scope = broken_scope
    with pytest.raises(RuntimeError):
        worker.run_reminders()
    assert not worker.reminders_due()
    clock[0] += timedelta(minutes=16)
    assert worker.reminders_due()


@pytest.mark.parametrize(
    ("red", "km", "expected"),
    [
        (120, 10_500, None),  # 105 %, до красного (12 000) — 1500 км > 1000
        (120, 11_200, ("due_soon", "до замены осталось 800 км")),
        (120, 12_100, ("overdue", "требуется замена")),
        (90, 8_500, ("due_soon", "до замены осталось 500 км")),
        (90, 9_100, ("overdue", "требуется замена")),
    ],
)
def test_reminder_counts_to_configured_red_threshold(
    client, admin, make_owner, make_worker, db, red, km, expected
):
    owner = make_owner("Zeekr")
    model = model_id(client, admin, "Zeekr")
    r = client.put(
        f"{API}/aggregate-status-thresholds",
        json={"yellow_from_percent": 50, "red_above_percent": red},
        headers=admin,
    )
    assert r.status_code == 200, r.text
    regulation(client, admin, model, "engine_oil", interval_km=10_000)
    replace(client, admin, owner.vehicle_id, "engine_oil", date(2026, 1, 10), 0)
    mileage(client, owner.headers, owner.vehicle_id, km)
    run_maintenance_reminders(db, make_worker().outbox, date(2026, 6, 1))
    got = reminders(db, owner.vehicle_id)
    if expected is None:
        assert got == []
    else:
        ((kind, text),) = got
        assert kind == expected[0] and expected[1] in text and "-" not in text.split(":")[1]


# ---------- Право на уведомление при отправке (Глава 17, ADR 0021 п. 5) ----------


def queued_reminder(client, admin, make_owner, make_worker, db: Session):
    """Клиент с авто и поставленным в очередь (не отправленным) напоминанием о ТО."""
    owner = make_owner("Zeekr")
    model = model_id(client, admin, "Zeekr")
    regulation(client, admin, model, "engine_oil", interval_km=10_000)
    replace(client, admin, owner.vehicle_id, "engine_oil", date(2026, 1, 10), 0)
    mileage(client, owner.headers, owner.vehicle_id, 12_000)
    worker = make_worker()
    assert run_maintenance_reminders(db, worker.outbox, date(2026, 6, 1)) == 1
    (notification_id,) = db.scalars(
        select(Notification.id).where(Notification.vehicle_id == owner.vehicle_id)
    )
    return owner, worker, notification_id


def test_queued_reminder_not_sent_after_vehicle_deleted(
    client, admin, make_owner, make_worker, sender, db: Session
):
    owner, worker, notification_id = queued_reminder(client, admin, make_owner, make_worker, db)
    r = client.delete(f"{API}/vehicles/{owner.vehicle_id}", headers=owner.headers)
    assert r.status_code == 204

    assert worker.dispatch() == 1
    (row,) = deliveries(db, notification_id)
    assert row.failed_at is not None and row.delivered_at is None
    assert row.error_code == "RECIPIENT_NOT_ELIGIBLE"
    assert row.attempts == 0
    assert sender.sent == []


@pytest.mark.parametrize("change", ["blocked", "consent_withdrawn", "anonymized"])
def test_queued_news_not_sent_to_ineligible_recipient(
    change, client, admin, make_owner, make_worker, sender, db: Session
):
    """Токен не отозван (изменение мимо API) — доставку закрывает повторная проверка права."""
    owner = make_owner(None)
    other = make_owner(None)
    news = publish(client, admin, type="news", message="Новость")
    user_id = client.get(f"{API}/me", headers=owner.headers).json()["id"]
    user = db.get(AppUser, user_id)
    if change == "blocked":
        user.is_active = False
    elif change == "consent_withdrawn":
        db.execute(
            update(PdConsent)
            .where(PdConsent.user_id == user_id)
            .values(withdrawn_at=datetime.now(UTC))
        )
    else:
        user.anonymized_at = datetime.now(UTC)
    db.commit()

    assert make_worker().dispatch() == 2
    by_token = {
        token: row
        for row in deliveries(db, news["id"])
        for token in db.scalars(select(PushToken.token).where(PushToken.id == row.push_token_id))
    }
    assert by_token[owner.token].error_code == "RECIPIENT_NOT_ELIGIBLE"
    assert by_token[other.token].delivered_at is not None
    assert sender.to(owner.token) == [] and len(sender.to(other.token)) == 1


def test_ticket_push_skips_deleted_vehicle(
    client, make_owner, make_worker, make_ticket, as_staff, sender, real_redis, settings
):
    owner = make_owner("Zeekr")
    ticket = make_ticket(owner.vehicle_id, as_staff("+375293490004")[1])
    r = client.delete(f"{API}/vehicles/{owner.vehicle_id}", headers=owner.headers)
    assert r.status_code == 204
    events = TicketEvents(real_redis, settings.redis_channel_prefix)
    make_worker().handle_message(
        events.channel(ticket.id), TicketUpdated(ticket_id=ticket.id).model_dump_json()
    )
    assert sender.sent == [], "тикет удалённого авто клиенту не виден — push нет"
