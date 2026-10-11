"""WebSocket событий тикета (ADR 0017 п. 9, docs/asyncapi.yaml): авторизация, доступ, события.

Подключение — Starlette TestClient; события идут через настоящий Redis pub/sub (тестовый
сервер). Кадры событий сверяются со схемами docs/openapi.yaml (`TicketMessage`, `Ticket`).
"""

import json
import time
from datetime import UTC, datetime, timedelta
from typing import Any

import anyio
import pytest
from fastapi.testclient import TestClient
from openapi_schema_validator import OAS30Validator
from redis import Redis
from redis.exceptions import ConnectionError as RedisConnectionError
from starlette.testclient import WebSocketTestSession
from starlette.websockets import WebSocketDisconnect

from app.core.config import Settings
from app.core.redis import get_redis
from app.core.security import create_access_token
from app.domain.tickets import events
from app.models import AppUser
from app.models.enums import UserRole
from tests.api.conftest import API, _inline, add_vehicle, api_settings

Headers = dict[str, str]
RECEIVE_TIMEOUT = 5.0

CLIENT_PHONE = "+375295500001"
ENGINEER_PHONE = "+375295500002"


@pytest.fixture
def settings() -> Settings:
    return api_settings(ws_auth_timeout_seconds=0.3)


@pytest.fixture
def owner(login_client) -> tuple[Headers, str]:
    token = login_client(CLIENT_PHONE)["access_token"]
    return {"Authorization": f"Bearer {token}"}, token


@pytest.fixture
def engineer(as_staff) -> tuple[Headers, str, AppUser]:
    headers, user = as_staff(ENGINEER_PHONE)
    return headers, headers["Authorization"].removeprefix("Bearer "), user


@pytest.fixture
def ticket_id(client: TestClient, owner) -> int:
    vehicle = add_vehicle(client, owner[0])
    r = client.post(
        f"{API}/tickets",
        json={"vehicle_id": vehicle["id"], "category": "sim", "description": "Нет сети"},
        headers=owner[0],
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


def receive(ws: WebSocketTestSession) -> dict[str, Any]:
    """Кадр сервера с тайм-аутом (TestClient ждёт бесконечно); закрытие — WebSocketDisconnect."""

    async def _receive() -> dict[str, Any]:
        with anyio.fail_after(RECEIVE_TIMEOUT):
            return await ws._send_rx.receive()

    message = ws.portal.call(_receive)
    if message["type"] == "websocket.close":
        raise WebSocketDisconnect(message.get("code", 1000))
    return message


def receive_event(ws: WebSocketTestSession) -> dict[str, Any]:
    return json.loads(receive(ws)["text"])


def close_code(ws: WebSocketTestSession) -> int:
    with pytest.raises(WebSocketDisconnect) as info:
        receive(ws)
    return info.value.code


def wait_subscribers(redis: Redis, ticket_id: int, count: int) -> None:
    """Подписка идёт после auth асинхронно: событие до неё не доставляется (at-most-once)."""
    channel = events.channel(ticket_id)
    deadline = time.monotonic() + RECEIVE_TIMEOUT
    while time.monotonic() < deadline:
        if dict(redis.pubsub_numsub(channel)).get(channel, 0) >= count:
            return
        time.sleep(0.01)
    raise AssertionError(f"нет {count} подписчиков {channel}")


def schema(name: str) -> dict:
    return _inline({"$ref": f"#/components/schemas/{name}"})


def assert_frame(frame: dict, event_type: str, schema_name: str) -> dict:
    assert set(frame) == {"type", "data"} and frame["type"] == event_type
    OAS30Validator(schema(schema_name)).validate(frame["data"])
    return frame["data"]


def connect(client: TestClient, ticket_id: int):
    return client.websocket_connect(f"{API}/tickets/{ticket_id}/ws")


# ---------- Авторизация ----------


def test_no_auth_within_timeout_closes_4401(client, ticket_id):
    with connect(client, ticket_id) as ws:
        assert close_code(ws) == 4401


@pytest.mark.parametrize(
    "frame",
    [
        "not json",
        '{"type": "subscribe"}',
        '{"type": "auth"}',
        '{"type": "auth", "access_token": ""}',
        '{"type": "auth", "access_token": "garbage"}',
        '{"type": "auth", "access_token": "x", "extra": 1}',
        '["auth", "token"]',
    ],
)
def test_bad_auth_frame_closes_4401(client, ticket_id, frame):
    with connect(client, ticket_id) as ws:
        ws.send_text(frame)
        assert close_code(ws) == 4401


def test_binary_auth_frame_closes_4401(client, ticket_id, owner):
    with connect(client, ticket_id) as ws:
        ws.send_bytes(f'{{"type":"auth","access_token":"{owner[1]}"}}'.encode())
        assert close_code(ws) == 4401


def test_invisible_ticket_closes_4403(client, ticket_id, login_client, engineer, as_staff):
    stranger = login_client("+375295500011")["access_token"]
    for tid, token in ((ticket_id, stranger), (10**9, engineer[1]), (2**63, engineer[1])):
        with connect(client, tid) as ws:
            ws.send_json({"type": "auth", "access_token": token})
            assert close_code(ws) == 4403


def test_inactive_user_closes_4401(client, ticket_id, engineer, db):
    engineer[2].is_active = False
    db.commit()
    with connect(client, ticket_id) as ws:
        ws.send_json({"type": "auth", "access_token": engineer[1]})
        assert close_code(ws) == 4401


def test_token_expiry_closes_4401(client, ticket_id, settings, engineer, real_redis):
    user = engineer[2]
    issued = datetime.now(UTC) - timedelta(seconds=settings.access_token_ttl_seconds - 2)
    token = create_access_token(user.id, user.role.value, settings, now=issued)
    with connect(client, ticket_id) as ws:
        ws.send_json({"type": "auth", "access_token": token})
        wait_subscribers(real_redis, ticket_id, 1)  # принят и подписан
        assert close_code(ws) == 4401


# ---------- События ----------


def test_message_created_is_rendered_per_recipient(
    client, ticket_id, owner, engineer, real_redis, as_staff
):
    eng_headers, eng_token, eng = engineer
    assert client.post(f"{API}/tickets/{ticket_id}/claim", headers=eng_headers).status_code == 200
    admin_headers, admin = as_staff("+375295500021", UserRole.ADMIN)
    admin_token = admin_headers["Authorization"].removeprefix("Bearer ")

    with (
        connect(client, ticket_id) as client_ws,
        connect(client, ticket_id) as eng_ws,
        connect(client, ticket_id) as admin_ws,
    ):
        client_ws.send_json({"type": "auth", "access_token": owner[1]})
        eng_ws.send_json({"type": "auth", "access_token": eng_token})
        admin_ws.send_json({"type": "auth", "access_token": admin_token})
        wait_subscribers(real_redis, ticket_id, 3)
        eng_ws.send_text("ping")  # прочие сообщения клиента игнорируются

        r = client.post(
            f"{API}/tickets/{ticket_id}/messages",
            json={"body": "Перезагрузите"},
            headers=eng_headers,
        )
        assert r.status_code == 201
        sent = r.json()

        seen_by_client = assert_frame(receive_event(client_ws), "message.created", "TicketMessage")
        seen_by_author = assert_frame(receive_event(eng_ws), "message.created", "TicketMessage")
        seen_by_admin = assert_frame(receive_event(admin_ws), "message.created", "TicketMessage")
        assert seen_by_author == sent, "автору — как ответ POST"
        assert seen_by_client["id"] == sent["id"] and seen_by_client["body"] == "Перезагрузите"
        assert (seen_by_client["author"]["phone"], seen_by_client["author"]["telegram_id"]) == (
            None,
            None,
        )
        assert seen_by_admin["author"]["phone"] == ENGINEER_PHONE

        r = client.post(
            f"{API}/tickets/{ticket_id}/messages", json={"body": "Сделал"}, headers=owner[0]
        )
        assert r.status_code == 201
        assert receive_event(eng_ws)["data"]["author"]["phone"] == CLIENT_PHONE
        assert receive_event(client_ws)["data"]["author"]["phone"] == CLIENT_PHONE
        assert receive_event(admin_ws)["data"]["body"] == "Сделал"

        r = client.patch(
            f"{API}/tickets/{ticket_id}/status",
            json={"status": "waiting_vendor"},
            headers=eng_headers,
        )
        assert r.status_code == 200
        for ws in (client_ws, eng_ws, admin_ws):
            ticket = assert_frame(receive_event(ws), "ticket.updated", "Ticket")
            assert ticket["status"] == "waiting_vendor"
    assert dict(real_redis.pubsub_numsub(events.channel(ticket_id))) == {
        events.channel(ticket_id): 0
    }, "подписки закрыты вместе с подключениями"


def test_reassignment_closes_lost_subscribers_4403(
    client, ticket_id, owner, engineer, as_staff, real_redis
):
    eng_headers, eng_token, _ = engineer
    admin_headers, _ = as_staff("+375295500031", UserRole.ADMIN)
    _, other = as_staff("+375295500032")

    with connect(client, ticket_id) as eng_ws, connect(client, ticket_id) as client_ws:
        eng_ws.send_json({"type": "auth", "access_token": eng_token})  # тикет в очереди
        client_ws.send_json({"type": "auth", "access_token": owner[1]})
        wait_subscribers(real_redis, ticket_id, 2)

        assert (
            client.post(f"{API}/tickets/{ticket_id}/claim", headers=eng_headers).status_code == 200
        )
        claimed = assert_frame(receive_event(eng_ws), "ticket.updated", "Ticket")
        assert claimed["status"] == "in_progress"
        assert (
            receive_event(client_ws)["data"]["assigned_engineer_id"]
            == claimed["assigned_engineer_id"]
        )

        r = client.patch(
            f"{API}/tickets/{ticket_id}/assign",
            json={"assigned_engineer_id": other.id},
            headers=admin_headers,
        )
        assert r.status_code == 200
        assert close_code(eng_ws) == 4403, "доступ потерян при переназначении"
        assert receive_event(client_ws)["data"]["assigned_engineer_id"] == other.id


def test_publish_failure_does_not_fail_request(client, ticket_id, owner, app, monkeypatch):
    def broken(*_: Any, **__: Any) -> None:
        raise RedisConnectionError("нет связи")

    redis = app.dependency_overrides[get_redis]()
    monkeypatch.setattr(redis, "publish", broken)
    r = client.post(f"{API}/tickets/{ticket_id}/messages", json={"body": "x"}, headers=owner[0])
    assert r.status_code == 201, "сообщение сохранено, клиент догрузит через after_id"


def test_event_parse_rejects_foreign_payloads():
    assert events.parse('{"type": "ticket.updated", "ticket_id": 5}') == events.TicketEvent(
        events.EventType.TICKET_UPDATED, 5
    )
    for raw in (
        "x",
        "[]",
        '{"type": "message.created", "ticket_id": 5}',
        '{"type": "unknown", "ticket_id": 5}',
        '{"type": "ticket.updated", "ticket_id": "5"}',
    ):
        assert events.parse(raw) is None, raw
