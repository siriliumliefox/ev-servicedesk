"""Запросы Tickets Service и Uploads для API-тестов (Глава 13, ADR 0017).

Обычный модуль без фикстур: участники (owner, engineer, admin) и их телефоны — в каждом
тестовом модуле свои. Помощники, ожидающие успех, сверяют ответ с docs/openapi.yaml.
"""

import re
from typing import Any

import httpx
from fastapi.testclient import TestClient

from app.core.storage import ObjectStorage
from tests.api.conftest import API, Headers, assert_contract
from tests.support.storage import put_object

JPEG = b"\xff\xd8\xff\xe0" + b"0" * 64
MP4 = b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 64
# Ключ загрузки: uploads/{user_id}/{uuid}{расширение по типу файла или ничего}.
UPLOAD_KEY = re.compile(r"uploads/(\d+)/([0-9a-f-]{36})(\.[a-z0-9]+)?")


def error_code(response: httpx.Response) -> str:
    return response.json()["error"]["code"]


# ---------- Загрузки ----------


def presign(
    client: TestClient, headers: Headers, name: str = "IMG 0001.JPG", file_type: str = "photo"
) -> dict[str, Any]:
    r = client.post(
        f"{API}/uploads/presign", json={"file_name": name, "file_type": file_type}, headers=headers
    )
    assert r.status_code == 200, r.text
    assert_contract(r, "createPresignedUpload")
    return r.json()


def put_upload(storage: ObjectStorage, presigned: dict[str, Any], data: bytes, mime: str) -> None:
    """Загрузка клиентом по выданному presigned PUT (в памяти — put())."""
    put_object(storage, presigned["file_url"], data, mime, presigned["upload_url"])


# ---------- Тикеты ----------


def create_ticket(
    client: TestClient, headers: Headers, vehicle_id: int, **extra: Any
) -> httpx.Response:
    body = {"vehicle_id": vehicle_id, "category": "navigation", "description": "Нет пробок"}
    return client.post(f"{API}/tickets", json=body | extra, headers=headers)


def create(client: TestClient, headers: Headers, vehicle_id: int, **extra: Any) -> dict:
    r = create_ticket(client, headers, vehicle_id, **extra)
    assert r.status_code == 201, r.text
    assert_contract(r, "createTicket")
    return r.json()


def items(client: TestClient, headers: Headers, **params: Any) -> list[dict]:
    r = client.get(f"{API}/tickets", params=params, headers=headers)
    assert r.status_code == 200, r.text
    assert_contract(r, "listTickets")
    return r.json()["items"]


def ids(client: TestClient, headers: Headers, **params: Any) -> list[int]:
    return [t["id"] for t in items(client, headers, **params)]


def card(client: TestClient, headers: Headers, tid: int) -> dict:
    r = client.get(f"{API}/tickets/{tid}", headers=headers)
    assert r.status_code == 200, r.text
    assert_contract(r, "getTicket")
    return r.json()


def claim(client: TestClient, headers: Headers, tid: int) -> dict:
    r = client.post(f"{API}/tickets/{tid}/claim", headers=headers)
    assert r.status_code == 200, r.text
    assert_contract(r, "claimTicket")
    return r.json()


def set_status(client: TestClient, headers: Headers, tid: int, status: str) -> dict:
    r = client.patch(f"{API}/tickets/{tid}/status", json={"status": status}, headers=headers)
    assert r.status_code == 200, r.text
    assert_contract(r, "updateTicketStatus")
    return r.json()


def assign(client: TestClient, admin: Headers, tid: int, engineer_id: int | None) -> dict:
    r = client.patch(
        f"{API}/tickets/{tid}/assign", json={"assigned_engineer_id": engineer_id}, headers=admin
    )
    assert r.status_code == 200, r.text
    assert_contract(r, "assignTicket")
    return r.json()


def say(client: TestClient, headers: Headers, tid: int, body: str) -> dict:
    r = client.post(f"{API}/tickets/{tid}/messages", json={"body": body}, headers=headers)
    assert r.status_code == 201, r.text
    assert_contract(r, "createTicketMessage")
    return r.json()


def history(client: TestClient, headers: Headers, tid: int, **params: Any) -> list[dict]:
    r = client.get(f"{API}/tickets/{tid}/messages", params=params, headers=headers)
    assert r.status_code == 200, r.text
    assert_contract(r, "listTicketMessages")
    return r.json()["items"]
