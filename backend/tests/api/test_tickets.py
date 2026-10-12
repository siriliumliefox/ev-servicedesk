"""Tickets Service (Глава 13, ADR 0017): API, доступ RBAC-04, граф статусов, чат, SLA.

Токены — настоящие (Глава 10): клиент входит по SMS-коду, персонал — по паролю. Вложения —
хранилище в памяти (`FakeObjectStorage`); полный цикл через MinIO —
tests/api/test_ticket_checklist.py. Каждый ответ сверяется с docs/openapi.yaml.
"""

from contextlib import AbstractContextManager
from datetime import UTC, date, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from redis import Redis
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import rate_limit
from app.core.config import get_settings
from app.core.errors import ApiError
from app.models import (
    AppUser,
    DecisionTreeNode,
    FirmwareRelease,
    KnowledgeArticle,
    Ticket,
    Vehicle,
)
from app.models.enums import KbArticleType, TicketStatus, UserRole
from tests.api.conftest import (
    API,
    UNKNOWN_VIN,
    Headers,
    add_vehicle,
    api_settings,
    assert_contract,
    model_id,
)
from tests.api.ticket_support import create, error_code

CLIENT_PHONE = "+375293300001"
ENGINEER_PHONE = "+375293300002"
ADMIN_PHONE = "+375293300003"


@pytest.fixture
def owner(as_client) -> Headers:
    return as_client(CLIENT_PHONE)


@pytest.fixture
def engineer(as_staff) -> tuple[Headers, AppUser]:
    return as_staff(ENGINEER_PHONE)


@pytest.fixture
def admin(as_staff) -> tuple[Headers, AppUser]:
    return as_staff(ADMIN_PHONE, UserRole.ADMIN)


@pytest.fixture
def vehicle(client: TestClient, owner: Headers) -> dict:
    return add_vehicle(client, owner)


# ---------- Основной сценарий ----------


def test_ticket_lifecycle(client, owner, engineer, admin, vehicle, db: Session):
    eng_headers, eng = engineer
    ticket = create(client, owner, vehicle["id"], description="  Яндекс Навигатор без пробок  ")
    tid = ticket["id"]
    assert ticket["status"] == "new" and ticket["assigned_engineer_id"] is None
    assert ticket["description"] == "Яндекс Навигатор без пробок", "пробелы по краям обрезаны"
    assert ticket["summary"] == ticket["description"]
    assert ticket["vehicle_model"] == {"brand": "Zeekr", "model": "001", "trim": None}
    assert ticket["vehicle_context"]["vehicle"]["id"] == vehicle["id"]
    assert ticket["is_overdue"] is False and ticket["resolved_at"] is None
    created = datetime.fromisoformat(ticket["created_at"])
    assert datetime.fromisoformat(ticket["sla_due_at"]) - created == timedelta(hours=8)

    # Очередь инженера: тикет виден до claim, писать в чат — нельзя.
    r = client.get(f"{API}/tickets", headers=eng_headers)
    assert_contract(r, "listTickets")
    assert [t["id"] for t in r.json()["items"]] == [tid]
    r = client.post(
        f"{API}/tickets/{tid}/messages", json={"body": "Здравствуйте"}, headers=eng_headers
    )
    assert r.status_code == 403
    assert_contract(r, "createTicketMessage")
    r = client.patch(
        f"{API}/tickets/{tid}/status", json={"status": "resolved"}, headers=eng_headers
    )
    assert r.status_code == 403
    assert_contract(r, "updateTicketStatus")

    r = client.post(f"{API}/tickets/{tid}/claim", headers=eng_headers)
    assert r.status_code == 200, r.text
    assert_contract(r, "claimTicket")
    assert (r.json()["status"], r.json()["assigned_engineer_id"]) == ("in_progress", eng.id)

    r = client.post(f"{API}/tickets/{tid}/messages", json={"body": "Здравствуйте!"}, headers=owner)
    assert r.status_code == 201, r.text
    assert_contract(r, "createTicketMessage")
    assert db.get(Ticket, tid).first_response_at is None, "сообщение клиента — не ответ"

    r = client.post(
        f"{API}/tickets/{tid}/messages", json={"body": "Проверьте версию"}, headers=eng_headers
    )
    assert r.status_code == 201, r.text
    staff_message = r.json()
    assert staff_message["author"]["phone"] == ENGINEER_PHONE, "автор видит себя полностью"
    first_response = db.scalar(select(Ticket.first_response_at).where(Ticket.id == tid))
    assert first_response is not None

    r = client.post(f"{API}/tickets/{tid}/messages", json={"body": "Ещё"}, headers=eng_headers)
    assert r.status_code == 201
    db.expire_all()
    assert db.get(Ticket, tid).first_response_at == first_response, "фиксируется однократно"

    # Клиенту ПД сотрудника скрыты, персоналу телефон клиента виден (ADR 0017 п. 12).
    r = client.get(f"{API}/tickets/{tid}/messages", headers=owner)
    assert_contract(r, "listTicketMessages")
    authors = [m["author"] for m in r.json()["items"]]
    assert [a["phone"] for a in authors] == [CLIENT_PHONE, None, None]
    assert all(a["telegram_id"] is None for a in authors)
    r = client.get(f"{API}/tickets/{tid}/messages", headers=admin[0])
    assert_contract(r, "listTicketMessages")
    assert [m["author"]["phone"] for m in r.json()["items"]] == [
        CLIENT_PHONE,
        ENGINEER_PHONE,
        ENGINEER_PHONE,
    ]

    r = client.patch(
        f"{API}/tickets/{tid}/status", json={"status": "resolved"}, headers=eng_headers
    )
    assert r.status_code == 200, r.text
    assert_contract(r, "updateTicketStatus")
    assert r.json()["status"] == "resolved" and r.json()["resolved_at"] is not None

    r = client.post(f"{API}/tickets/{tid}/messages", json={"body": "Спасибо"}, headers=owner)
    assert r.status_code == 409
    assert_contract(r, "createTicketMessage")
    assert error_code(r) == "TICKET_RESOLVED"

    # Переоткрытие: resolved_at очищается, срок SLA прежний.
    r = client.patch(
        f"{API}/tickets/{tid}/status", json={"status": "in_progress"}, headers=eng_headers
    )
    assert r.status_code == 200
    body = r.json()
    assert (body["status"], body["resolved_at"]) == ("in_progress", None)
    assert body["sla_due_at"] == ticket["sla_due_at"]


def test_detail_has_firmware_snapshot_and_aggregate_context(
    client, owner, admin, vehicle, db: Session
):
    zeekr = db.get(Vehicle, vehicle["id"])
    old, new = (
        FirmwareRelease(
            vehicle_model_id=zeekr.vehicle_model_id, version=v, released_at=date.today()
        )
        for v in ("1.2.0", "1.3.0")
    )
    db.add_all([old, new])
    db.flush()
    zeekr.current_firmware_release_id = old.id
    db.commit()
    r = client.post(
        f"{API}/maintenance-regulations",
        json={
            "vehicle_model_id": zeekr.vehicle_model_id,
            "aggregate_type_code": "cabin_filter",
            "interval_km": 15000,
        },
        headers=admin[0],
    )
    assert r.status_code == 201, r.text

    ticket = create(client, owner, vehicle["id"])
    zeekr.current_firmware_release_id = new.id
    db.commit()

    r = client.get(f"{API}/tickets/{ticket['id']}", headers=owner)
    assert r.status_code == 200
    assert_contract(r, "getTicket")
    detail = r.json()
    assert detail["firmware_version_at_creation"] == "1.2.0", "снимок на момент создания"
    assert detail["vehicle_context"]["vehicle"]["current_firmware_version"] == "1.3.0"
    r = client.get(f"{API}/vehicles/{vehicle['id']}/aggregate-statuses", headers=owner)
    assert detail["vehicle_context"]["aggregate_statuses"] == r.json()["items"]
    assert [s["aggregate_type_code"] for s in r.json()["items"]] == ["cabin_filter"]


# ---------- Создание ----------


def test_create_requires_own_active_vehicle(client, owner, as_client, vehicle):
    stranger = as_client("+375293300011")
    r = client.post(
        f"{API}/tickets",
        json={"vehicle_id": vehicle["id"], "category": "sim", "description": "x"},
        headers=stranger,
    )
    assert r.status_code == 404
    assert_contract(r, "createTicket")

    r = client.delete(f"{API}/vehicles/{vehicle['id']}", headers=owner)
    assert r.status_code == 204
    r = client.post(
        f"{API}/tickets",
        json={"vehicle_id": vehicle["id"], "category": "sim", "description": "x"},
        headers=owner,
    )
    assert r.status_code == 404
    for vid in (0, 2**63):
        r = client.post(
            f"{API}/tickets",
            json={"vehicle_id": vid, "category": "sim", "description": "x"},
            headers=owner,
        )
        assert r.status_code == 404


def test_create_is_client_only(client, engineer, vehicle):
    r = client.post(
        f"{API}/tickets",
        json={"vehicle_id": vehicle["id"], "category": "sim", "description": "x"},
        headers=engineer[0],
    )
    assert r.status_code == 403
    assert_contract(r, "createTicket")


@pytest.mark.parametrize("description", ["", "   ", "a" * 4001, "нуль\x00"])
def test_create_validates_description(client, owner, vehicle, description):
    r = client.post(
        f"{API}/tickets",
        json={"vehicle_id": vehicle["id"], "category": "sim", "description": description},
        headers=owner,
    )
    assert r.status_code == 422
    assert_contract(r, "createTicket")


def test_description_limit_is_after_trimming(client, owner, vehicle):
    text = "я" * 4000
    ticket = create(client, owner, vehicle["id"], description=f"  {text}\n")
    assert ticket["description"] == text
    assert ticket["summary"] == text[:140]
    multiline = create(client, owner, vehicle["id"], description="Строка 1\nСтрока 2\tконец")
    assert multiline["description"] == "Строка 1\nСтрока 2\tконец"


def test_source_reference_validation(client, owner, vehicle, db: Session):
    article, other, draft = (
        KnowledgeArticle(article_type=KbArticleType.TROUBLESHOOTING, title=t, is_published=t != "C")
        for t in "ABC"
    )
    db.add_all([article, other, draft])
    db.flush()
    node = DecisionTreeNode(article_id=article.id, question_text="Перезагрузили?", is_root=True)
    foreign = DecisionTreeNode(article_id=other.id, question_text="Есть сеть?", is_root=True)
    draft_node = DecisionTreeNode(article_id=draft.id, question_text="Черновик?", is_root=True)
    db.add_all([node, foreign, draft_node])
    db.commit()

    ticket = create(
        client, owner, vehicle["id"], source_article_id=article.id, source_node_id=node.id
    )
    assert db.get(Ticket, ticket["id"]).source_node_id == node.id
    create(client, owner, vehicle["id"], source_article_id=article.id)

    bodies = []
    for refs in (
        {"source_node_id": node.id},  # узел без статьи
        {"source_article_id": 10**9},
        {"source_article_id": 2**63},
        {"source_article_id": article.id, "source_node_id": foreign.id},
        {"source_article_id": article.id, "source_node_id": 10**9},
        # Черновик для клиента не существует: тот же 422, что и отсутствующая статья.
        {"source_article_id": draft.id},
        {"source_article_id": draft.id, "source_node_id": draft_node.id},
    ):
        r = client.post(
            f"{API}/tickets",
            json={"vehicle_id": vehicle["id"], "category": "sim", "description": "x"} | refs,
            headers=owner,
        )
        assert r.status_code == 422, refs
        assert_contract(r, "createTicket")
        assert error_code(r) == "INVALID_SOURCE_REFERENCE"
        bodies.append(r.json())
    # Ответ на черновик неотличим от ответа на отсутствующую статью (не раскрывает черновики).
    assert bodies[-2] == bodies[1]


def test_create_rate_limit(client, app, owner, vehicle):
    limited = api_settings(ticket_create_per_user_hour=2)
    app.dependency_overrides[get_settings] = lambda: limited
    create(client, owner, vehicle["id"])
    create(client, owner, vehicle["id"])
    r = client.post(
        f"{API}/tickets",
        json={"vehicle_id": vehicle["id"], "category": "sim", "description": "x"},
        headers=owner,
    )
    assert r.status_code == 429
    assert_contract(r, "createTicket")
    assert int(r.headers["Retry-After"]) >= 1


def test_rejected_attempt_is_returned_to_window(real_redis: Redis):
    """Отказ 429 тоже возвращает свою попытку: счётчик = успешные + выполняющиеся.

    Лимит 2: одно создание прошло, попытка A выполняется, B получает 429, A падает с 422 —
    создано одно, поэтому следующая попытка проходит (ADR 0017, «Уточнения»: лимит — на
    успешные создания).
    """

    def counted() -> AbstractContextManager[None]:
        return rate_limit.reserve(real_redis, "ticket-create:test-429", 3600, 2, "Лимит")

    with counted():
        pass
    with pytest.raises(ApiError) as failed, counted():
        with pytest.raises(ApiError) as rejected, counted():
            pass
        assert rejected.value.status_code == 429
        raise ApiError(422, "ATTACHMENT_NOT_FOUND", "Файл не найден")
    assert failed.value.status_code == 422
    with counted():
        pass


# ---------- Видимость (RBAC-04) ----------


def test_visibility(client, owner, as_client, as_staff, engineer, admin, vehicle, make_ticket):
    eng_headers, eng = engineer
    other_headers, other_eng = as_staff("+375293300021")
    stranger = as_client("+375293300022")
    queue = create(client, owner, vehicle["id"])
    mine = make_ticket(vehicle["id"], eng)
    theirs = make_ticket(vehicle["id"], other_eng)

    def ids(headers: Headers) -> set[int]:
        r = client.get(f"{API}/tickets", headers=headers)
        assert_contract(r, "listTickets")
        return {t["id"] for t in r.json()["items"]}

    assert ids(owner) == {queue["id"], mine.id, theirs.id}
    assert ids(stranger) == set()
    assert ids(eng_headers) == {queue["id"], mine.id}
    assert ids(admin[0]) == {queue["id"], mine.id, theirs.id}

    for headers, tid in ((eng_headers, theirs.id), (stranger, queue["id"])):
        r = client.get(f"{API}/tickets/{tid}", headers=headers)
        assert r.status_code == 404
        assert_contract(r, "getTicket")
        r = client.get(f"{API}/tickets/{tid}/messages", headers=headers)
        assert r.status_code == 404
        assert_contract(r, "listTicketMessages")
        r = client.post(f"{API}/tickets/{tid}/messages", json={"body": "x"}, headers=headers)
        assert r.status_code == 404
        assert_contract(r, "createTicketMessage")
    r = client.patch(
        f"{API}/tickets/{theirs.id}/status", json={"status": "resolved"}, headers=eng_headers
    )
    assert r.status_code == 404
    for tid in (0, 2**63):
        r = client.get(f"{API}/tickets/{tid}", headers=admin[0])
        assert r.status_code == 404

    # Удалённое авто: тикеты клиенту не видны, персоналу — видны.
    assert client.delete(f"{API}/vehicles/{vehicle['id']}", headers=owner).status_code == 204
    assert ids(owner) == set()
    assert client.get(f"{API}/tickets/{mine.id}", headers=eng_headers).status_code == 200


def test_list_filters_order_and_overdue(client, owner, engineer, admin, vehicle, make_ticket, db):
    eng = engineer[1]
    late = make_ticket(vehicle["id"], eng)
    late.sla_due_at = datetime.now(UTC) - timedelta(hours=1)
    resolved_late = make_ticket(vehicle["id"], eng, TicketStatus.RESOLVED)
    resolved_late.sla_due_at = datetime.now(UTC) - timedelta(hours=2)
    db.commit()
    crash = create(client, owner, vehicle["id"], category="app_crash")  # 4 ч
    audio = create(client, owner, vehicle["id"], category="audio")  # 24 ч

    def ids(headers: Headers, **params) -> list[int]:
        r = client.get(f"{API}/tickets", params=params, headers=headers)
        assert r.status_code == 200, r.text
        assert_contract(r, "listTickets")
        return [t["id"] for t in r.json()["items"]]

    staff = admin[0]
    assert ids(staff) == [resolved_late.id, late.id, crash["id"], audio["id"]], "по sla_due_at"
    assert ids(owner) == [audio["id"], crash["id"], resolved_late.id, late.id], "новые первыми"
    assert ids(staff, overdue=True) == [late.id]
    assert ids(staff, overdue=False) == [resolved_late.id, crash["id"], audio["id"]]
    assert ids(staff, status="new") == [crash["id"], audio["id"]]
    assert ids(staff, category="audio") == [audio["id"]]
    assert ids(staff, assigned_engineer_id=eng.id) == [resolved_late.id, late.id]
    assert ids(owner, overdue=True) == [late.id]

    r = client.get(f"{API}/tickets", params={"overdue": True}, headers=staff)
    [item] = r.json()["items"]
    assert item["is_overdue"] is True
    r = client.get(f"{API}/tickets", params={"status": "closed"}, headers=staff)
    assert r.status_code == 422
    assert_contract(r, "listTickets")
    r = client.get(f"{API}/tickets", params={"page_size": 1, "page": 2}, headers=staff)
    assert r.json()["meta"] == {"page": 2, "page_size": 1, "total_items": 4, "total_pages": 4}


# ---------- Claim, статус, назначение ----------


def test_claim_rules(client, owner, engineer, as_staff, vehicle):
    eng_headers, eng = engineer
    other_headers, _ = as_staff("+375293300031")
    tid = create(client, owner, vehicle["id"])["id"]

    assert client.post(f"{API}/tickets/{tid}/claim", headers=eng_headers).status_code == 200
    r = client.post(f"{API}/tickets/{tid}/claim", headers=eng_headers)
    assert r.status_code == 200, "повторный claim своего — без изменений"
    assert r.json()["assigned_engineer_id"] == eng.id

    r = client.post(f"{API}/tickets/{tid}/claim", headers=other_headers)
    assert r.status_code == 409
    assert_contract(r, "claimTicket")
    assert error_code(r) == "TICKET_ALREADY_CLAIMED"

    for missing in (10**9, 0, 2**63):
        r = client.post(f"{API}/tickets/{missing}/claim", headers=eng_headers)
        assert r.status_code == 404
        assert_contract(r, "claimTicket")
    r = client.post(f"{API}/tickets/{tid}/claim", headers=owner)
    assert r.status_code == 403


def test_status_graph_via_api(client, engineer, admin, vehicle, make_ticket):
    eng_headers, eng = engineer
    ticket = make_ticket(vehicle["id"], eng)

    def patch(status: str, headers: Headers = eng_headers):
        r = client.patch(
            f"{API}/tickets/{ticket.id}/status", json={"status": status}, headers=headers
        )
        assert_contract(r, "updateTicketStatus")
        return r

    assert patch("in_progress").status_code == 200, "текущий статус — без изменений"
    assert patch("waiting_vendor").json()["status"] == "waiting_vendor"
    r = patch("new")
    assert r.status_code == 409 and error_code(r) == "INVALID_STATUS_TRANSITION"
    assert patch("resolved").json()["status"] == "resolved"
    r = patch("waiting_vendor")
    assert r.status_code == 409
    assert patch("in_progress", admin[0]).json()["status"] == "in_progress"
    assert patch("bogus").status_code == 422


def test_admin_cannot_move_queue_ticket_by_status(client, owner, admin, vehicle):
    tid = create(client, owner, vehicle["id"])["id"]
    r = client.patch(
        f"{API}/tickets/{tid}/status", json={"status": "in_progress"}, headers=admin[0]
    )
    assert r.status_code == 409
    assert error_code(r) == "INVALID_STATUS_TRANSITION"


def test_assign_rules(client, owner, engineer, as_staff, admin, make_staff, vehicle, as_client):
    _, eng = engineer
    _, other = as_staff("+375293300041")
    blocked = make_staff("+375293300042", active=False)
    admin_headers, admin_user = admin
    tid = create(client, owner, vehicle["id"])["id"]

    def assign(engineer_id, headers: Headers = admin_headers):
        r = client.patch(
            f"{API}/tickets/{tid}/assign",
            json={"assigned_engineer_id": engineer_id},
            headers=headers,
        )
        assert_contract(r, "assignTicket")
        return r

    r = assign(eng.id)
    assert r.status_code == 200, r.text
    assert (r.json()["status"], r.json()["assigned_engineer_id"]) == ("in_progress", eng.id)
    r = assign(other.id)
    assert (r.json()["status"], r.json()["assigned_engineer_id"]) == ("in_progress", other.id)
    client_user_id = client.get(f"{API}/me", headers=owner).json()["id"]
    for bad in (admin_user.id, blocked.id, client_user_id, 10**9, -1):
        r = assign(bad)
        assert r.status_code == 422, bad
        assert error_code(r) == "ASSIGNEE_NOT_ENGINEER"
    assert assign(2**63).status_code == 422
    r = assign(None)
    assert (r.json()["status"], r.json()["assigned_engineer_id"]) == ("new", None)

    r = client.patch(f"{API}/tickets/{tid}/assign", json={}, headers=admin_headers)
    assert r.status_code == 422, "поле обязательно: null — явное снятие"
    assert assign(eng.id, engineer[0]).status_code == 403
    assert (
        client.patch(
            f"{API}/tickets/{10**9}/assign",
            json={"assigned_engineer_id": None},
            headers=admin_headers,
        ).status_code
        == 404
    )

    assign(eng.id)
    r = client.patch(
        f"{API}/tickets/{tid}/status", json={"status": "resolved"}, headers=admin_headers
    )
    assert r.status_code == 200
    r = assign(other.id)
    assert r.status_code == 409 and error_code(r) == "TICKET_RESOLVED"


# ---------- Чат ----------


def test_messages_after_id_and_pagination(client, owner, admin, vehicle):
    tid = create(client, owner, vehicle["id"])["id"]
    ids = []
    for i in range(5):
        r = client.post(f"{API}/tickets/{tid}/messages", json={"body": f"№{i}"}, headers=owner)
        assert r.status_code == 201
        ids.append(r.json()["id"])
    # Админ пишет в любой тикет, в т. ч. в очередь (RBAC-04).
    r = client.post(f"{API}/tickets/{tid}/messages", json={"body": "Админ"}, headers=admin[0])
    assert r.status_code == 201
    ids.append(r.json()["id"])

    def page(**params) -> dict:
        r = client.get(f"{API}/tickets/{tid}/messages", params=params, headers=owner)
        assert r.status_code == 200, r.text
        assert_contract(r, "listTicketMessages")
        return r.json()

    assert [m["id"] for m in page()["items"]] == ids
    assert [m["id"] for m in page(after_id=ids[2])["items"]] == ids[3:]
    body = page(after_id=ids[1], page_size=2, page=2)
    assert [m["id"] for m in body["items"]] == ids[4:6]
    assert body["meta"]["total_items"] == 4
    assert page(after_id=0)["meta"]["total_items"] == 6
    r = client.get(f"{API}/tickets/{tid}/messages", params={"after_id": -1}, headers=owner)
    assert r.status_code == 422
    assert_contract(r, "listTicketMessages")


@pytest.mark.parametrize("body", ["", "  \n ", "б" * 4001])
def test_message_body_validation(client, owner, vehicle, body):
    tid = create(client, owner, vehicle["id"])["id"]
    r = client.post(f"{API}/tickets/{tid}/messages", json={"body": body}, headers=owner)
    assert r.status_code == 422
    assert_contract(r, "createTicketMessage")


def test_message_rate_limit(client, app, owner, vehicle):
    tid = create(client, owner, vehicle["id"])["id"]
    limited = api_settings(ticket_message_per_user_minute=2)
    app.dependency_overrides[get_settings] = lambda: limited
    for _ in range(2):
        assert (
            client.post(
                f"{API}/tickets/{tid}/messages", json={"body": "x"}, headers=owner
            ).status_code
            == 201
        )
    r = client.post(f"{API}/tickets/{tid}/messages", json={"body": "x"}, headers=owner)
    assert r.status_code == 429
    assert_contract(r, "createTicketMessage")
    assert int(r.headers["Retry-After"]) >= 1


def test_client_of_other_model_sees_model_info(client, as_client):
    headers = as_client("+375293300051")
    li = add_vehicle(
        client, headers, UNKNOWN_VIN, vehicle_model_id=model_id(client, headers, "Li Auto")
    )
    ticket = create(client, headers, li["id"])
    assert ticket["vehicle_model"]["brand"] == "Li Auto"


def test_rejected_attempts_do_not_consume_limit(client, app, owner, vehicle):
    """Лимит — на созданные тикеты (ADR 0017 п. 7): исправленный запрос проходит без 429."""
    app.dependency_overrides[get_settings] = lambda: api_settings(ticket_create_per_user_hour=1)
    for _ in range(3):
        r = client.post(
            f"{API}/tickets",
            json={
                "vehicle_id": vehicle["id"],
                "category": "sim",
                "description": "x",
                "source_article_id": 10**9,
            },
            headers=owner,
        )
        assert r.status_code == 422
    create(client, owner, vehicle["id"])
    r = client.post(
        f"{API}/tickets",
        json={"vehicle_id": vehicle["id"], "category": "sim", "description": "x"},
        headers=owner,
    )
    assert r.status_code == 429
