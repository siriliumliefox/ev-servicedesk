"""Проверки чек-листа Главы 13 (ADR 0017): полный цикл тикета и SLA-просрочка.

«Интеграционный тест полного цикла тикета» — на настоящих токенах Auth (клиент входит по
SMS-коду, персонал — по паролю) и настоящем S3 API (MinIO): presign → PUT → тикет с фото →
очередь → claim → чат в обе стороны → замена агрегата (Глава 12) → статусы → переоткрытие →
переназначение и снятие исполнителя → история чата → список клиента.
«Тест SLA: просроченный тикет помечается корректно» — нормативы читаются из
`ticket_sla_policy` (миграция 0008), а не дублируются в тесте.

Тест идёт в одной внешней транзакции (tests/api/conftest.py): `now()` PostgreSQL — время её
начала — одинаково для всех запросов теста. Поэтому граница просрочки проверяется точно,
однократность первичного ответа — через подмену значения в БД, а порядок по created_at —
через явную правку created_at.
"""

from datetime import date, datetime, timedelta
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.core.time import today_in_business_tz
from app.models import (
    AppUser,
    FirmwareRelease,
    MaintenanceRecord,
    Ticket,
    TicketSlaPolicy,
    Vehicle,
)
from app.models.enums import TicketCategory, UserRole
from tests.api.conftest import API, UNKNOWN_VIN, Headers, add_vehicle, model_id
from tests.api.ticket_support import (
    assign,
    card,
    claim,
    create,
    error_code,
    history,
    ids,
    items,
    presign,
    put_upload,
    say,
    set_status,
)

OWNER_PHONE = "+375296600001"
STRANGER_PHONE = "+375296600002"
ENGINEER_PHONE = "+375296600003"
SECOND_ENGINEER_PHONE = "+375296600004"
ADMIN_PHONE = "+375296600005"

PHOTO = b"\xff\xd8\xff\xe0" + bytes(range(256)) * 2


@pytest.fixture
def owner(as_client) -> Headers:
    return as_client(OWNER_PHONE)


@pytest.fixture
def engineer(as_staff) -> tuple[Headers, AppUser]:
    return as_staff(ENGINEER_PHONE)


@pytest.fixture
def admin(as_staff) -> Headers:
    return as_staff(ADMIN_PHONE, UserRole.ADMIN)[0]


@pytest.fixture
def vehicle(client: TestClient, owner: Headers) -> dict:
    return add_vehicle(client, owner)


@pytest.fixture
def policy(db: Session) -> dict[TicketCategory, timedelta]:
    """Нормативы SLA из таблицы: категория → срок решения."""
    rows = db.execute(select(TicketSlaPolicy.category, TicketSlaPolicy.resolution_minutes))
    return {category: timedelta(minutes=minutes) for category, minutes in rows}


# ---------- Запросы ----------


def ts(value: str) -> datetime:
    return datetime.fromisoformat(value)


def aggregate_statuses(client: TestClient, headers: Headers, vid: int) -> list[dict]:
    r = client.get(f"{API}/vehicles/{vid}/aggregate-statuses", headers=headers)
    assert r.status_code == 200, r.text
    return r.json()["items"]


# ---------- Состояние в БД ----------


def db_now(db: Session) -> datetime:
    return db.scalar(select(func.now()))


def first_response_at(db: Session, tid: int) -> datetime | None:
    return db.scalar(select(Ticket.first_response_at).where(Ticket.id == tid))


def set_ticket(db: Session, tid: int, **values: Any) -> None:
    """Правка строки в обход API: срок SLA, created_at и первичный ответ API не меняет."""
    db.execute(
        update(Ticket)
        .where(Ticket.id == tid)
        .values(**values)
        .execution_options(synchronize_session=False)
    )
    db.commit()


# ---------- Интеграционный тест полного цикла тикета ----------


def test_full_ticket_lifecycle(
    client, db: Session, owner, as_client, engineer, as_staff, admin, vehicle, minio, policy
):
    eng_headers, eng = engineer
    eng2_headers, eng2 = as_staff(SECOND_ENGINEER_PHONE)
    stranger = as_client(STRANGER_PHONE)
    vid = vehicle["id"]

    # Контекст авто: текущая прошивка (снимок N-09), пробег, регламент масла (Глава 12).
    zeekr = db.get(Vehicle, vid)
    firmware = FirmwareRelease(
        vehicle_model_id=zeekr.vehicle_model_id, version="2.4.1", released_at=date.today()
    )
    db.add(firmware)
    db.flush()
    zeekr.current_firmware_release_id = firmware.id
    db.commit()
    r = client.patch(f"{API}/vehicles/{vid}/mileage", json={"mileage": 21000}, headers=owner)
    assert r.status_code == 200, r.text
    r = client.post(
        f"{API}/maintenance-regulations",
        json={
            "vehicle_model_id": zeekr.vehicle_model_id,
            "aggregate_type_code": "engine_oil",
            "interval_km": 10000,
        },
        headers=admin,
    )
    assert r.status_code == 201, r.text

    # 1. Клиент: фото по presigned PUT в MinIO → тикет с вложением и контекстом авто.
    upload = presign(client, owner, name="IMG_0420.JPG")
    put_upload(minio, upload, PHOTO, "image/jpeg")
    ticket = create(
        client,
        owner,
        vid,
        category="app_crash",
        description="Приложение закрывается сразу после запуска",
        attachments=[{"file_url": upload["file_url"], "file_type": "photo"}],
    )
    tid = ticket["id"]
    assert (ticket["status"], ticket["assigned_engineer_id"]) == ("new", None)
    assert (ticket["resolved_at"], ticket["is_overdue"]) == (None, False)
    assert ts(ticket["sla_due_at"]) - ts(ticket["created_at"]) == policy[TicketCategory.APP_CRASH]
    assert ticket["vehicle_model"] == {"brand": "Zeekr", "model": "001", "trim": None}
    assert ticket["firmware_version_at_creation"] == "2.4.1"
    context = ticket["vehicle_context"]
    assert (context["vehicle"]["id"], context["vehicle"]["mileage"]) == (vid, 21000)
    assert context["vehicle"]["current_firmware_version"] == "2.4.1"
    assert context["aggregate_statuses"] == aggregate_statuses(client, owner, vid)
    [oil] = context["aggregate_statuses"]
    assert (oil["aggregate_type_code"], oil["status"]) == ("engine_oil", "unknown")
    [photo] = ticket["attachments"]
    assert photo["file_type"] == "photo"
    got = httpx.get(photo["file_url"])
    assert got.status_code == 200 and got.content == PHOTO, "presigned GET отдаёт то же фото"

    li_auto = model_id(client, stranger, "Li Auto")
    foreign_vehicle = add_vehicle(client, stranger, UNKNOWN_VIN, vehicle_model_id=li_auto)
    foreign = create(client, stranger, foreign_vehicle["id"], category="navigation")

    # 2. Очередь инженера: тикет и карточка видны до claim. Клиент пишет и в new, но его
    # сообщение — не первичный ответ.
    assert tid in ids(client, eng_headers, status="new")
    assert card(client, eng_headers, tid)["vehicle_context"]["vehicle"]["id"] == vid
    m1 = say(client, owner, tid, "Падает сразу после заставки")
    assert first_response_at(db, tid) is None

    # 3. Claim: тикет у первого инженера; второй его больше не видит, а его claim — 409.
    claimed = claim(client, eng_headers, tid)
    assert (claimed["status"], claimed["assigned_engineer_id"]) == ("in_progress", eng.id)
    r = client.get(f"{API}/tickets/{tid}", headers=eng2_headers)
    assert r.status_code == 404
    r = client.post(f"{API}/tickets/{tid}/claim", headers=eng2_headers)
    assert r.status_code == 409
    assert error_code(r) == "TICKET_ALREADY_CLAIMED"
    assert tid not in ids(client, eng2_headers)
    assert ids(client, eng_headers, assigned_engineer_id=eng.id) == [tid]

    # 4. Чат в обе стороны; первичный ответ — первое сообщение персонала, однократно.
    m2 = say(client, eng_headers, tid, "Здравствуйте! Какая версия приложения?")
    first = first_response_at(db, tid)
    assert first is not None
    # now() в транзакции теста постоянен: повторная запись дала бы то же значение. Подменяем
    # зафиксированное — следующие ответы персонала его не трогают.
    marker = first - timedelta(minutes=7)
    set_ticket(db, tid, first_response_at=marker)
    m3 = say(client, owner, tid, "Последняя, из магазина приложений")
    m4 = say(client, eng_headers, tid, "Сбросьте кеш; масло заменим по этому же тикету")
    assert first_response_at(db, tid) == marker

    # 5. Замена агрегата инженером (Глава 12) сразу видна в карточке тикета.
    r = client.post(
        f"{API}/vehicles/{vid}/aggregate-statuses/engine_oil/replace",
        json={"replaced_at": str(today_in_business_tz()), "mileage_at_replacement": 21000},
        headers=eng_headers,
    )
    assert r.status_code == 200, r.text
    for headers in (owner, eng_headers):
        context = card(client, headers, tid)["vehicle_context"]
        [oil] = context["aggregate_statuses"]
        assert (oil["status"], oil["last_replaced_mileage"], oil["remaining_km"]) == (
            "green",
            21000,
            10000,
        )
        assert context["aggregate_statuses"] == aggregate_statuses(client, headers, vid)
    record = db.scalars(select(MaintenanceRecord).where(MaintenanceRecord.vehicle_id == vid)).one()
    assert record.ticket_id == tid, "замена привязана к тикету инженера"

    # 6. in_progress → waiting_vendor → in_progress → resolved.
    assert set_status(client, eng_headers, tid, "waiting_vendor")["status"] == "waiting_vendor"
    assert set_status(client, eng_headers, tid, "in_progress")["status"] == "in_progress"
    resolved = set_status(client, eng_headers, tid, "resolved")
    assert resolved["status"] == "resolved" and resolved["resolved_at"] is not None
    assert card(client, owner, tid)["resolved_at"] == resolved["resolved_at"]
    for headers in (owner, eng_headers):
        r = client.post(f"{API}/tickets/{tid}/messages", json={"body": "Спасибо!"}, headers=headers)
        assert r.status_code == 409
        assert error_code(r) == "TICKET_RESOLVED"

    # 7. Переоткрытие: resolved_at очищается, срок SLA прежний.
    reopened = set_status(client, eng_headers, tid, "in_progress")
    assert (reopened["status"], reopened["resolved_at"]) == ("in_progress", None)
    assert reopened["sla_due_at"] == ticket["sla_due_at"]
    assert card(client, owner, tid)["resolved_at"] is None

    # 8. Переназначение админом: первый инженер теряет доступ (404), второй — получает.
    body = assign(client, admin, tid, eng2.id)
    assert (body["status"], body["assigned_engineer_id"]) == ("in_progress", eng2.id)
    r = client.get(f"{API}/tickets/{tid}", headers=eng_headers)
    assert r.status_code == 404
    r = client.post(f"{API}/tickets/{tid}/messages", json={"body": "Ещё"}, headers=eng_headers)
    assert r.status_code == 404
    r = client.patch(
        f"{API}/tickets/{tid}/status", json={"status": "resolved"}, headers=eng_headers
    )
    assert r.status_code == 404
    assert tid not in ids(client, eng_headers)
    m5 = say(client, eng2_headers, tid, "Тикет у меня, продолжаем")
    assert first_response_at(db, tid) == marker

    # 9. Снятие исполнителя: тикет снова в очереди (new) — виден обоим инженерам.
    body = assign(client, admin, tid, None)
    assert (body["status"], body["assigned_engineer_id"]) == ("new", None)
    for headers in (eng_headers, eng2_headers):
        assert tid in ids(client, headers, status="new")
        assert card(client, headers, tid)["status"] == "new"

    # 10. История: по возрастанию id; after_id — догрузка после переподключения.
    sent = [m1, m2, m3, m4, m5]
    sent_ids = [m["id"] for m in sent]
    assert sent_ids == sorted(sent_ids)
    for headers in (owner, admin):
        messages = history(client, headers, tid)
        assert [m["id"] for m in messages] == sent_ids
        assert [m["body"] for m in messages] == [m["body"] for m in sent]
    authors = [m["author"]["phone"] for m in history(client, owner, tid)]
    assert authors == [OWNER_PHONE, None, OWNER_PHONE, None, None], "ПД персонала скрыты"
    assert [m["id"] for m in history(client, owner, tid, after_id=m2["id"])] == sent_ids[2:]
    assert history(client, owner, tid, after_id=m5["id"]) == []

    # 11. Список клиента — только свои тикеты, новые (по created_at) первыми.
    later = create(client, owner, vid, category="sim", description="Нет мобильной сети")
    assert ids(client, owner) == [later["id"], tid]
    # Порядок — по created_at, а не по id: созданный раньше идёт ниже, даже с большим id.
    set_ticket(db, later["id"], created_at=func.now() - timedelta(days=1))
    assert ids(client, owner) == [tid, later["id"]]
    assert ids(client, stranger) == [foreign["id"]]


# ---------- Тест SLA: просроченный тикет помечается корректно ----------


def test_sla_due_follows_policy_for_every_category(client, db: Session, owner, vehicle, policy):
    assert set(policy) == set(TicketCategory), "норматив задан для каждой категории"
    for category in TicketCategory:
        ticket = create(client, owner, vehicle["id"], category=category.value)
        assert ts(ticket["sla_due_at"]) - ts(ticket["created_at"]) == policy[category], category
        assert ticket["is_overdue"] is False
        created_at, due = db.execute(
            select(Ticket.created_at, Ticket.sla_due_at).where(Ticket.id == ticket["id"])
        ).one()
        assert due - created_at == policy[category], category


def test_policy_change_does_not_move_existing_due(client, db: Session, owner, vehicle, policy):
    before = create(client, owner, vehicle["id"], category="sim")
    changed = policy[TicketCategory.SIM] + timedelta(minutes=90)
    db.execute(
        update(TicketSlaPolicy)
        .where(TicketSlaPolicy.category == TicketCategory.SIM)
        .values(resolution_minutes=changed // timedelta(minutes=1))
    )
    db.commit()

    after = create(client, owner, vehicle["id"], category="sim")
    assert ts(after["sla_due_at"]) - ts(after["created_at"]) == changed, "новый — по новому"
    assert card(client, owner, before["id"])["sla_due_at"] == before["sla_due_at"]
    listed = {t["id"]: t["sla_due_at"] for t in items(client, owner)}
    assert listed[before["id"]] == before["sla_due_at"]


def test_overdue_ticket_is_marked_in_list_and_detail(
    client, db: Session, owner, engineer, admin, vehicle
):
    late = create(client, owner, vehicle["id"])["id"]
    fresh = create(client, owner, vehicle["id"])["id"]
    set_ticket(db, late, sla_due_at=func.now() - timedelta(seconds=1))

    for headers in (owner, engineer[0], admin):  # инженеру оба видны в очереди
        assert card(client, headers, late)["is_overdue"] is True
        assert card(client, headers, fresh)["is_overdue"] is False
        assert {t["id"]: t["is_overdue"] for t in items(client, headers)} == {
            late: True,
            fresh: False,
        }
        assert ids(client, headers, overdue=True) == [late]
        assert ids(client, headers, overdue=False) == [fresh]


def test_overdue_boundary_is_strict(client, db: Session, owner, admin, vehicle):
    """now() > sla_due_at: срок, равный now() транзакции, ещё не просрочен."""
    tid = create(client, owner, vehicle["id"])["id"]
    now = db_now(db)
    for offset, overdue in (
        (timedelta(0), False),
        (timedelta(microseconds=-1), True),
        (timedelta(microseconds=1), False),
        (timedelta(seconds=-1), True),
        (timedelta(seconds=1), False),
    ):
        set_ticket(db, tid, sla_due_at=now + offset)
        assert card(client, admin, tid)["is_overdue"] is overdue, offset
        assert (tid in ids(client, admin, overdue=True)) is overdue, offset
        assert (tid in ids(client, admin, overdue=False)) is not overdue, offset
    assert db_now(db) == now, "граница детерминирована: now() постоянен в транзакции теста"


def test_resolved_is_not_overdue_and_reopened_is_again(
    client, db: Session, owner, engineer, admin, vehicle
):
    eng_headers, _ = engineer
    tid = create(client, owner, vehicle["id"])["id"]
    claim(client, eng_headers, tid)
    set_ticket(db, tid, sla_due_at=func.now() - timedelta(hours=1))
    assert card(client, eng_headers, tid)["is_overdue"] is True

    # Ожидание вендора срок не останавливает (ADR 0017 п. 1).
    assert set_status(client, eng_headers, tid, "waiting_vendor")["is_overdue"] is True
    assert ids(client, admin, overdue=True) == [tid]

    resolved = set_status(client, eng_headers, tid, "resolved")
    assert resolved["is_overdue"] is False, "решённый не просрочен, даже если решён поздно"
    assert card(client, owner, tid)["is_overdue"] is False
    assert {t["id"]: t["is_overdue"] for t in items(client, owner)} == {tid: False}
    assert ids(client, admin, overdue=True) == []
    assert ids(client, admin, overdue=False) == [tid]

    reopened = set_status(client, eng_headers, tid, "in_progress")
    assert reopened["is_overdue"] is True, "переоткрытие срок не продлевает"
    assert reopened["sla_due_at"] == resolved["sla_due_at"]
    assert card(client, owner, tid)["is_overdue"] is True
    assert ids(client, admin, overdue=True) == [tid]


def test_staff_list_is_ordered_by_sla_due(client, owner, engineer, admin, vehicle, policy):
    """Приоритет — из категории через срок SLA (ADR 0017 п. 3): app_crash, созданный после
    audio, у персонала выше; клиенту — новые первыми."""
    assert policy[TicketCategory.APP_CRASH] < policy[TicketCategory.AUDIO]
    order = (
        TicketCategory.AUDIO,
        TicketCategory.MAINTENANCE,
        TicketCategory.APP_CRASH,
        TicketCategory.NAVIGATION,
        TicketCategory.SIM,
    )
    created = {c: create(client, owner, vehicle["id"], category=c.value)["id"] for c in order}
    expected = [created[c] for c in sorted(order, key=lambda c: (policy[c], created[c]))]

    for headers in (admin, engineer[0]):  # у инженера — очередь
        listed = items(client, headers)
        assert [t["id"] for t in listed] == expected
        dues = [ts(t["sla_due_at"]) for t in listed]
        assert dues == sorted(dues)
        listed_ids = [t["id"] for t in listed]
        assert listed_ids.index(created[TicketCategory.APP_CRASH]) < listed_ids.index(
            created[TicketCategory.AUDIO]
        )
    # created_at в транзакции теста одинаков — клиенту по убыванию id, не по сроку.
    assert ids(client, owner) == sorted(created.values(), reverse=True)
