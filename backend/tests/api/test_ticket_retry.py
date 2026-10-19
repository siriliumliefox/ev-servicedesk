"""Повтор создания тикета и сообщения по ключу `client_request_id` (#111, ADR 0031).

Клиент после обрыва связи повторяет запрос с ключом черновика: сервер, уже записавший тикет или
сообщение, отвечает записанным — без дубля, без второго события message.created и без учёта в
лимите. Тот же ключ с другим содержимым — 422 CLIENT_REQUEST_ID_REUSED.

Гонки исходного запроса и повтора здесь воспроизводятся детерминированно: первая проверка ключа
повтора подменяется на «не найдено» (повтор начался до commit исходного) — так проходятся ветки
«найдено под блокировкой», «UNIQUE ключа» и «загрузки уже привязаны». Настоящие одновременные
запросы — tests/api/test_ticket_concurrency.py.
"""

import uuid
from collections.abc import Callable
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import get_ticket_events
from app.core.config import get_settings
from app.core.storage import ObjectStorage
from app.domain.tickets import service
from app.domain.tickets.events import TicketEvents
from app.models import AppUser, Ticket, TicketAttachment, TicketMessage
from app.models.enums import UserRole
from tests.api.conftest import API, Headers, add_vehicle, api_settings, error_code
from tests.api.ticket_support import JPEG, claim, presign, put_upload, set_status

CLIENT_PHONE = "+375293300101"
OTHER_CLIENT_PHONE = "+375293300102"
ENGINEER_PHONE = "+375293300103"
OTHER_ENGINEER_PHONE = "+375293300104"
ADMIN_PHONE = "+375293300105"


class RecordedEvents(TicketEvents):
    """События сценария без Redis: id сообщений из message.created."""

    def __init__(self) -> None:
        self.created: list[int] = []

    def message_created(self, ticket_id: int, message_id: int) -> None:
        self.created.append(message_id)

    def ticket_updated(self, ticket_id: int) -> None:
        pass


@pytest.fixture
def events(app) -> RecordedEvents:
    recorded = RecordedEvents()
    app.dependency_overrides[get_ticket_events] = lambda: recorded
    return recorded


@pytest.fixture
def owner(as_client) -> Headers:
    return as_client(CLIENT_PHONE)


@pytest.fixture
def vehicle(client: TestClient, owner: Headers) -> dict:
    return add_vehicle(client, owner)


@pytest.fixture
def engineer(as_staff) -> tuple[Headers, AppUser]:
    return as_staff(ENGINEER_PHONE)


def key() -> str:
    return str(uuid.uuid4())


def new_ticket(vehicle_id: int, request_id: str | None, **extra: Any) -> dict:
    body = {"vehicle_id": vehicle_id, "category": "navigation", "description": "Нет пробок"}
    if request_id is not None:
        body["client_request_id"] = request_id
    return body | extra


def post_ticket(client: TestClient, headers: Headers, body: dict):
    return client.post(f"{API}/tickets", json=body, headers=headers)


def post_message(
    client: TestClient,
    headers: Headers,
    ticket_id: int,
    body: str,
    request_id: str | None,
    attachments: list[dict] | None = None,
):
    payload: dict[str, Any] = {"body": body, "attachments": attachments or []}
    if request_id is not None:
        payload["client_request_id"] = request_id
    return client.post(f"{API}/tickets/{ticket_id}/messages", json=payload, headers=headers)


def uploaded(client: TestClient, headers: Headers, storage: ObjectStorage) -> list[dict]:
    target = presign(client, headers)
    put_upload(storage, target, JPEG, "image/jpeg")
    return [{"file_url": target["file_url"], "file_type": "photo"}]


def count(db: Session, model: type, *where: Any) -> int:
    return db.scalar(select(func.count()).select_from(model).where(*where))


def first_lookup_misses(monkeypatch, name: str) -> list[int | None]:
    """Первая проверка ключа (до записи) «не видит» исходный запрос; результаты — в списке."""
    real: Callable[..., int | None] = getattr(service, name)
    results: list[int | None] = []

    def lookup(*args: Any, **kwargs: Any) -> int | None:
        found = None if not results else real(*args, **kwargs)
        results.append(found)
        return found

    monkeypatch.setattr(service, name, lookup)
    return results


@pytest.fixture
def ticket_id(client: TestClient, owner: Headers, vehicle: dict) -> int:
    r = post_ticket(client, owner, new_ticket(vehicle["id"], None))
    assert r.status_code == 201, r.text
    return r.json()["id"]


# ---------- Сообщение ----------


def test_message_retry_returns_sent_message(client, owner, ticket_id, events, db: Session):
    request_id = key()
    first = post_message(client, owner, ticket_id, "Не грузится карта", request_id)
    assert first.status_code == 201, first.text
    again = post_message(client, owner, ticket_id, "  Не грузится карта \n", request_id)
    assert again.status_code == 201, again.text
    assert again.json() == first.json(), "повтор — тот же ответ, текст сравнивается после обрезки"
    assert count(db, TicketMessage, TicketMessage.ticket_id == ticket_id) == 1
    assert events.created == [first.json()["id"]], "message.created — однократно"

    # Без ключа — прежнее поведение: каждое сообщение новое.
    for _ in range(2):
        assert post_message(client, owner, ticket_id, "Ещё", None).status_code == 201
    assert count(db, TicketMessage, TicketMessage.ticket_id == ticket_id) == 3


def test_message_key_with_other_body_is_rejected(client, owner, ticket_id, db: Session):
    request_id = key()
    assert post_message(client, owner, ticket_id, "Первое", request_id).status_code == 201
    r = post_message(client, owner, ticket_id, "Другое", request_id)
    assert r.status_code == 422
    assert error_code(r) == "CLIENT_REQUEST_ID_REUSED"
    assert r.json()["error"]["details"]["fields"] == [{"loc": ["body", "client_request_id"]}]
    assert count(db, TicketMessage, TicketMessage.ticket_id == ticket_id) == 1


def test_message_key_scope_is_ticket_and_author(
    client, owner, vehicle, ticket_id, as_staff, db: Session
):
    admin_headers, _ = as_staff(ADMIN_PHONE, UserRole.ADMIN)
    other = post_ticket(client, owner, new_ticket(vehicle["id"], None)).json()["id"]
    request_id = key()
    assert post_message(client, owner, ticket_id, "Привет", request_id).status_code == 201
    # Тот же ключ у другого автора и в другом тикете — другие сообщения.
    assert post_message(client, admin_headers, ticket_id, "Привет", request_id).status_code == 201
    assert post_message(client, owner, other, "Привет", request_id).status_code == 201
    assert count(db, TicketMessage, TicketMessage.client_request_id == uuid.UUID(request_id)) == 3


def test_message_retry_after_ticket_resolved(client, owner, ticket_id, engineer):
    eng_headers, _ = engineer
    claim(client, eng_headers, ticket_id)
    request_id = key()
    sent = post_message(client, owner, ticket_id, "Помогло", request_id).json()
    set_status(client, eng_headers, ticket_id, "resolved")
    again = post_message(client, owner, ticket_id, "Помогло", request_id)
    assert (again.status_code, again.json()["id"]) == (201, sent["id"])
    r = post_message(client, owner, ticket_id, "Помогло", key())
    assert (r.status_code, error_code(r)) == (409, "TICKET_RESOLVED")


def test_message_retry_does_not_reveal_invisible_ticket(
    client, owner, ticket_id, engineer, as_staff
):
    """Инженер, с которого сняли тикет, повтором своего сообщения тикет не видит — 404."""
    eng_headers, _ = engineer
    admin_headers, _ = as_staff(ADMIN_PHONE, UserRole.ADMIN)
    _, other_engineer = as_staff(OTHER_ENGINEER_PHONE)
    claim(client, eng_headers, ticket_id)
    request_id = key()
    assert post_message(client, eng_headers, ticket_id, "Смотрю", request_id).status_code == 201
    r = client.patch(
        f"{API}/tickets/{ticket_id}/assign",
        json={"assigned_engineer_id": other_engineer.id},
        headers=admin_headers,
    )
    assert r.status_code == 200, r.text
    r = post_message(client, eng_headers, ticket_id, "Смотрю", request_id)
    assert (r.status_code, error_code(r)) == (404, "NOT_FOUND")


def test_message_retry_is_not_rate_limited(client, app, owner, ticket_id):
    app.dependency_overrides[get_settings] = lambda: api_settings(ticket_message_per_user_minute=1)
    request_id = key()
    assert post_message(client, owner, ticket_id, "Раз", request_id).status_code == 201
    assert post_message(client, owner, ticket_id, "Раз", request_id).status_code == 201
    assert post_message(client, owner, ticket_id, "Два", key()).status_code == 429


def test_message_retry_with_attachment_after_upload_is_bound(
    client, owner, ticket_id, storage: ObjectStorage, events, db: Session
):
    """Загрузку исходный запрос уже привязал и удалил: повтор отвечает записанным, а не 422."""
    attachments = uploaded(client, owner, storage)
    request_id = key()
    first = post_message(client, owner, ticket_id, "Фото", request_id, attachments)
    assert first.status_code == 201, first.text
    again = post_message(client, owner, ticket_id, "Фото", request_id, attachments)
    assert (again.status_code, again.json()["id"]) == (201, first.json()["id"])
    assert len(again.json()["attachments"]) == 1
    assert count(db, TicketAttachment, TicketAttachment.ticket_id == ticket_id) == 1
    assert events.created == [first.json()["id"]]


def test_message_retry_started_before_commit_finds_message_under_lock(
    client, owner, ticket_id, events, monkeypatch, db: Session
):
    """Повтор ждал блокировку тикета: под ней видна запись исходного — попытка откатывается."""
    request_id = key()
    sent = post_message(client, owner, ticket_id, "Жду", request_id).json()
    lookups = first_lookup_misses(monkeypatch, "_sent_message_id")
    again = post_message(client, owner, ticket_id, "Жду", request_id)
    assert (again.status_code, again.json()) == (201, sent)
    assert lookups == [None, sent["id"]], "вторая проверка — под блокировкой строки тикета"
    assert count(db, TicketMessage, TicketMessage.ticket_id == ticket_id) == 1
    assert events.created == [sent["id"]]


def test_message_retry_started_before_commit_with_bound_upload(
    client, owner, ticket_id, storage: ObjectStorage, monkeypatch, db: Session
):
    """Повтор проверил ключ до commit исходного, а загрузку тот уже привязал — 201, не 422."""
    attachments = uploaded(client, owner, storage)
    request_id = key()
    sent = post_message(client, owner, ticket_id, "Фото", request_id, attachments).json()
    lookups = first_lookup_misses(monkeypatch, "_sent_message_id")
    again = post_message(client, owner, ticket_id, "Фото", request_id, attachments)
    assert (again.status_code, again.json()["id"]) == (201, sent["id"])
    assert lookups == [None, sent["id"]], "после 422 ATTACHMENT_NOT_FOUND"
    assert count(db, TicketAttachment, TicketAttachment.ticket_id == ticket_id) == 1


@pytest.mark.parametrize("value", ["draft-1", "", "123"])
def test_client_request_id_must_be_uuid(client, owner, vehicle, ticket_id, value):
    r = post_message(client, owner, ticket_id, "x", value)
    assert r.status_code == 422
    r = post_ticket(client, owner, new_ticket(vehicle["id"], value))
    assert r.status_code == 422


# ---------- Тикет ----------


def test_ticket_retry_returns_created_ticket(client, owner, vehicle, db: Session):
    request_id = key()
    first = post_ticket(client, owner, new_ticket(vehicle["id"], request_id))
    assert first.status_code == 201, first.text
    again = post_ticket(client, owner, new_ticket(vehicle["id"], request_id))
    assert again.status_code == 201, again.text
    assert again.json() == first.json()
    assert count(db, Ticket, Ticket.vehicle_id == vehicle["id"]) == 1


def test_ticket_key_with_other_content_is_rejected(client, owner, vehicle, db: Session):
    request_id = key()
    assert post_ticket(client, owner, new_ticket(vehicle["id"], request_id)).status_code == 201
    for changed in ({"description": "Нет звука"}, {"category": "audio"}):
        r = post_ticket(client, owner, new_ticket(vehicle["id"], request_id, **changed))
        assert (r.status_code, error_code(r)) == (422, "CLIENT_REQUEST_ID_REUSED"), changed
    assert count(db, Ticket, Ticket.vehicle_id == vehicle["id"]) == 1


def test_ticket_key_scope_is_vehicle(client, owner, vehicle, as_client, db: Session):
    request_id = key()
    second = add_vehicle(client, owner, vin="L6TZ0010000013111")
    other_owner = as_client(OTHER_CLIENT_PHONE)
    third = add_vehicle(client, other_owner, vin="L6TZ0010000013112")
    ids = {
        post_ticket(client, headers, new_ticket(v["id"], request_id)).json()["id"]
        for headers, v in ((owner, vehicle), (owner, second), (other_owner, third))
    }
    assert len(ids) == 3
    # Чужое авто с тем же ключом — 404, как без ключа (существование не раскрывается).
    r = post_ticket(client, other_owner, new_ticket(vehicle["id"], request_id))
    assert (r.status_code, error_code(r)) == (404, "NOT_FOUND")
    assert count(db, Ticket, Ticket.client_request_id == uuid.UUID(request_id)) == 3


def test_ticket_retry_is_not_rate_limited(client, app, owner, vehicle):
    app.dependency_overrides[get_settings] = lambda: api_settings(ticket_create_per_user_hour=1)
    request_id = key()
    assert post_ticket(client, owner, new_ticket(vehicle["id"], request_id)).status_code == 201
    assert post_ticket(client, owner, new_ticket(vehicle["id"], request_id)).status_code == 201
    assert post_ticket(client, owner, new_ticket(vehicle["id"], key())).status_code == 429


def test_ticket_retry_with_attachment_after_upload_is_bound(
    client, owner, vehicle, storage: ObjectStorage, db: Session
):
    body = new_ticket(vehicle["id"], key(), attachments=uploaded(client, owner, storage))
    first = post_ticket(client, owner, body)
    assert first.status_code == 201, first.text
    again = post_ticket(client, owner, body)
    assert (again.status_code, again.json()["id"]) == (201, first.json()["id"])
    assert len(again.json()["attachments"]) == 1
    assert count(db, Ticket, Ticket.vehicle_id == vehicle["id"]) == 1


def test_ticket_retry_started_before_commit_stops_at_unique_key(
    client, owner, vehicle, monkeypatch, db: Session
):
    """Создание не упорядочено блокировкой (FOR SHARE авто): дубль останавливает UNIQUE ключа."""
    body = new_ticket(vehicle["id"], key())
    created = post_ticket(client, owner, body).json()
    lookups = first_lookup_misses(monkeypatch, "_created_ticket_id")
    again = post_ticket(client, owner, body)
    assert (again.status_code, again.json()) == (201, created)
    assert lookups == [None, created["id"]], "после IntegrityError по UNIQUE ключа"
    assert count(db, Ticket, Ticket.vehicle_id == vehicle["id"]) == 1


def test_ticket_retry_started_before_commit_with_bound_upload(
    client, owner, vehicle, storage: ObjectStorage, monkeypatch, db: Session
):
    body = new_ticket(vehicle["id"], key(), attachments=uploaded(client, owner, storage))
    created = post_ticket(client, owner, body).json()
    lookups = first_lookup_misses(monkeypatch, "_created_ticket_id")
    again = post_ticket(client, owner, body)
    assert (again.status_code, again.json()["id"]) == (201, created["id"])
    assert lookups == [None, created["id"]], "после 422 ATTACHMENT_NOT_FOUND"
    assert count(db, Ticket, Ticket.vehicle_id == vehicle["id"]) == 1
