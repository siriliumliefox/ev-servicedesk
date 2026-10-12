"""WebSocket событий тикета (ADR 0017 п. 9, docs/asyncapi.yaml): авторизация, доступ, события.

Подключение — Starlette TestClient; события идут через настоящий Redis pub/sub (тестовый
сервер). Кадры событий сверяются со схемами docs/openapi.yaml (`TicketMessage`, `Ticket`).
Приложение запущено (`with TestClient(app)`): все подключения работают в одном цикле событий
и делят одно соединение подписки, как в процессе uvicorn.
"""

import json
import logging
import time
from datetime import UTC, datetime, timedelta
from typing import Any

import anyio
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from openapi_schema_validator import OAS30Validator
from redis import Redis
from redis.asyncio.client import PubSub
from redis.exceptions import ConnectionError as RedisConnectionError
from sqlalchemy.exc import OperationalError
from starlette.testclient import WebSocketTestSession
from starlette.websockets import WebSocketDisconnect

from app.api.deps import get_ticket_events
from app.api.routes import ticket_events
from app.core import rate_limit
from app.core.config import Settings
from app.core.pubsub import PubSubHub, get_pubsub_hub
from app.core.redis import get_redis
from app.core.security import create_access_token
from app.domain.tickets import events
from app.domain.tickets.events import TicketEvents
from app.main import create_app
from app.models import AppUser
from app.models.enums import UserRole
from tests.api.conftest import API, RUN_CHANNEL_PREFIX, _inline, add_vehicle, api_settings

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
    """Следующий кадр события; служебный `ready` пропускается (его проверяет wait_ready)."""
    while (frame := json.loads(receive(ws)["text"])) == READY:
        pass
    return frame


READY = {"type": "ready"}


def wait_ready(ws: WebSocketTestSession) -> None:
    """Кадр `ready`: подписка подтверждена Redis и доступ проверен — события не теряются."""
    assert json.loads(receive(ws)["text"]) == READY


def auth(ws: WebSocketTestSession, token: str) -> None:
    ws.send_json({"type": "auth", "access_token": token})
    wait_ready(ws)


def assert_quiet(ws: WebSocketTestSession, seconds: float = 0.3) -> None:
    """За `seconds` подключению ничего не пришло (ни кадра, ни закрытия)."""

    async def _poll() -> dict[str, Any] | None:
        with anyio.move_on_after(seconds):
            return await ws._send_rx.receive()
        return None

    assert ws.portal.call(_poll) is None, "лишний кадр"


def close_code(ws: WebSocketTestSession) -> int:
    with pytest.raises(WebSocketDisconnect) as info:
        receive(ws)
    return info.value.code


def run_events(redis: Redis) -> TicketEvents:
    """События тикетов в каналах прогона — как у приложения с `api_settings`."""
    return TicketEvents(redis, RUN_CHANNEL_PREFIX)


def numsub(redis: Redis, ticket_id: int) -> int:
    channel = run_events(redis).channel(ticket_id)
    return dict(redis.pubsub_numsub(channel)).get(channel, 0)


def schema(name: str) -> dict:
    return _inline({"$ref": f"#/components/schemas/{name}"})


def assert_frame(frame: dict, event_type: str, schema_name: str) -> dict:
    assert set(frame) == {"type", "data"} and frame["type"] == event_type
    OAS30Validator(schema(schema_name)).validate(frame["data"])
    return frame["data"]


def connect(client: TestClient, ticket_id: int | str):
    return client.websocket_connect(f"{API}/tickets/{ticket_id}/ws")


def hub_of(app: FastAPI) -> PubSubHub:
    """Общая подписка запущенного приложения (lifespan, app.main)."""
    return app.state.pubsub_hub


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


@pytest.mark.parametrize("tid", ["abc", "1.5", "1e3", "0x1", "-1", "１２"])
def test_non_integer_ticket_id_closes_4403(client, engineer, tid):
    """Не id тикета — как тикета нет: 4403 («не переподключаться»), а не 1008 до accept."""
    with connect(client, tid) as ws:
        ws.send_json({"type": "auth", "access_token": engineer[1]})
        assert close_code(ws) == 4403
    with connect(client, tid) as ws:  # без auth — как для любого тикета
        assert close_code(ws) == 4401


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
        auth(ws, token)  # принят и подписан
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
        auth(client_ws, owner[1])
        auth(eng_ws, eng_token)
        auth(admin_ws, admin_token)
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
    wait_until(lambda: numsub(real_redis, ticket_id) == 0, "подписки не закрыты с подключениями")


def test_reassignment_closes_lost_subscribers_4403(
    client, ticket_id, owner, engineer, as_staff, real_redis
):
    eng_headers, eng_token, _ = engineer
    admin_headers, _ = as_staff("+375295500031", UserRole.ADMIN)
    _, other = as_staff("+375295500032")

    with connect(client, ticket_id) as eng_ws, connect(client, ticket_id) as client_ws:
        auth(eng_ws, eng_token)  # тикет в очереди
        auth(client_ws, owner[1])

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
    assert events.parse('{"type": "ticket.updated", "ticket_id": 5}') == events.TicketUpdated(
        ticket_id=5
    )
    for raw in (
        "x",
        "[]",
        '{"type": "message.created", "ticket_id": 5}',
        '{"type": "unknown", "ticket_id": 5}',
        '{"type": "ticket.updated", "ticket_id": "5"}',
    ):
        assert events.parse(raw) is None, raw


# ---------- Готовность и пространство имён каналов ----------


def ticket_updated_payload(ticket_id: int) -> str:
    return json.dumps({"type": "ticket.updated", "ticket_id": ticket_id})


def test_ready_is_sent_once_after_subscription(client, ticket_id, owner, real_redis):
    """`ready` — первый кадр и только после SUBSCRIBE: событие сразу после него не теряется."""
    with connect(client, ticket_id) as ws:
        ws.send_json({"type": "auth", "access_token": owner[1]})
        assert json.loads(receive(ws)["text"]) == READY
        assert real_redis.publish(
            run_events(real_redis).channel(ticket_id), ticket_updated_payload(ticket_id)
        )
        assert_frame(json.loads(receive(ws)["text"]), "ticket.updated", "Ticket")
        assert_quiet(ws)


def test_channel_prefix_defaults_to_environment(monkeypatch, settings, real_redis):
    monkeypatch.delenv("REDIS_CHANNEL_PREFIX", raising=False)
    assert get_ticket_events(real_redis, settings).channel(7) == f"{RUN_CHANNEL_PREFIX}:ticket:7"
    assert Settings(_env_file=None).redis_channel_prefix == "ev-servicedesk:local"
    assert (
        Settings(_env_file=None, environment="test").redis_channel_prefix == "ev-servicedesk:test"
    )
    assert Settings(_env_file=None, redis_channel_prefix="stand-2").redis_channel_prefix == (
        "stand-2"
    )


def test_foreign_namespace_events_are_not_delivered(client, ticket_id, owner, real_redis):
    """Другой стенд (или прогон тестов) на том же сервере Redis: каналы не пересекаются."""
    with connect(client, ticket_id) as ws:
        auth(ws, owner[1])
        for foreign in (f"ticket:{ticket_id}", f"other-stand:ticket:{ticket_id}"):
            real_redis.publish(foreign, ticket_updated_payload(ticket_id))
        assert_quiet(ws)


# ---------- Общее соединение подписки и лимиты подключений ----------


def wait_until(predicate, what: str) -> None:
    deadline = time.monotonic() + RECEIVE_TIMEOUT
    while not predicate():
        if time.monotonic() > deadline:
            raise AssertionError(what)
        time.sleep(0.01)


def test_one_pubsub_connection_per_process(client, ticket_id, owner, engineer, real_redis):
    """Подключения процесса делят одно соединение: SUBSCRIBE на первом, UNSUBSCRIBE на последнем."""
    vehicle_id = client.get(f"{API}/tickets/{ticket_id}", headers=owner[0]).json()["vehicle_id"]
    r = client.post(
        f"{API}/tickets",
        json={"vehicle_id": vehicle_id, "category": "audio", "description": "Второй"},
        headers=owner[0],
    )
    assert r.status_code == 201, r.text
    other_id = r.json()["id"]

    with connect(client, ticket_id) as first, connect(client, ticket_id) as second:
        auth(first, owner[1])
        auth(second, owner[1])
        with connect(client, other_id) as other:
            auth(other, owner[1])
            assert (numsub(real_redis, ticket_id), numsub(real_redis, other_id)) == (1, 1)
        wait_until(lambda: numsub(real_redis, other_id) == 0, "нет UNSUBSCRIBE")
        assert numsub(real_redis, ticket_id) == 1

        r = client.post(f"{API}/tickets/{ticket_id}/claim", headers=engineer[0])
        assert r.status_code == 200, r.text
        for ws in (first, second):
            assert assert_frame(receive_event(ws), "ticket.updated", "Ticket")["status"] == (
                "in_progress"
            )
    wait_until(lambda: numsub(real_redis, ticket_id) == 0, "соединение подписки не закрыто")


def test_lifespan_creates_process_hub(app, client, ticket_id, owner):
    """Без подмены зависимости: подписка процесса из lifespan (app.main), закрытие при остановке."""
    assert isinstance(app.state.pubsub_hub, PubSubHub)
    with connect(client, ticket_id) as ws:
        auth(ws, owner[1])


def test_apps_in_one_process_each_deliver(app, client, settings, ticket_id, owner, engineer):
    other_app = create_app(settings)  # своя общая подписка — из своего lifespan
    other_app.dependency_overrides.update(app.dependency_overrides)

    with TestClient(other_app) as second:
        with connect(client, ticket_id) as one, connect(second, ticket_id) as two:
            auth(one, owner[1])
            auth(two, owner[1])
            r = second.post(f"{API}/tickets/{ticket_id}/claim", headers=engineer[0])
            assert r.status_code == 200, r.text
            for ws in (one, two):
                assert_frame(receive_event(ws), "ticket.updated", "Ticket")


def test_user_socket_cap_closes_4429(client, ticket_id, owner, settings, monkeypatch):
    monkeypatch.setattr(settings, "ws_max_sockets_per_user", 2)
    with connect(client, ticket_id) as first, connect(client, ticket_id) as second:
        auth(first, owner[1])
        auth(second, owner[1])
        with connect(client, ticket_id) as third:
            third.send_json({"type": "auth", "access_token": owner[1]})
            assert close_code(third) == 4429
    with connect(client, ticket_id) as again:  # закрытые подключения освобождают место
        auth(again, owner[1])


def test_connect_attempts_per_ip_close_4429(client, ticket_id, owner, settings, monkeypatch):
    monkeypatch.setattr(settings, "ws_connects_per_ip_minute", 2)
    for _ in range(2):
        with connect(client, ticket_id) as ws:
            auth(ws, owner[1])
    with connect(client, ticket_id) as ws:
        assert close_code(ws) == 4429, "лимит попыток — до auth"


def test_slow_consumer_closes_1013(app, client, ticket_id, owner, real_redis, monkeypatch):
    """Очередь получателя ограничена: не успевающий — закрытие 1013, а не рост памяти."""
    monkeypatch.setattr(hub_of(app), "queue_size", 1)
    render = ticket_events._render

    def slow(*args: Any) -> Any:
        time.sleep(0.3)
        return render(*args)

    monkeypatch.setattr(ticket_events, "_render", slow)
    with connect(client, ticket_id) as ws:
        auth(ws, owner[1])
        for _ in range(5):
            real_redis.publish(
                run_events(real_redis).channel(ticket_id), ticket_updated_payload(ticket_id)
            )
        frames = 0
        with pytest.raises(WebSocketDisconnect) as info:
            while True:
                receive(ws)
                frames += 1
        assert info.value.code == 1013 and frames < 5


# ---------- Сбои инфраструктуры: 1011, а не обрыв TCP ----------


def test_unanswered_ping_closes_1011(app, client, ticket_id, owner, monkeypatch):
    """Полуоткрытое соединение с Redis (PING без ответа) не держит подключения вечно."""
    monkeypatch.setattr(hub_of(app), "ping_seconds", 0.2)
    execute = PubSub.execute_command

    async def lossy(self: PubSub, *args: Any) -> Any:
        if args[0] == "PING":
            return None  # пакет потерян: ответа не будет
        return await execute(self, *args)

    monkeypatch.setattr(PubSub, "execute_command", lossy)
    with connect(client, ticket_id) as ws:
        auth(ws, owner[1])
        assert close_code(ws) == 1011


def test_link_loss_closes_sockets_1011_and_recovers(app, client, ticket_id, owner, monkeypatch):
    monkeypatch.setattr(hub_of(app), "ping_seconds", 0.2)  # чтение не дольше 0,2 с
    broken = {"now": False}
    get_message = PubSub.get_message

    async def flaky(self: PubSub, *args: Any, **kwargs: Any) -> Any:
        if broken["now"]:
            raise RedisConnectionError("обрыв")
        return await get_message(self, *args, **kwargs)

    monkeypatch.setattr(PubSub, "get_message", flaky)
    with connect(client, ticket_id) as first, connect(client, ticket_id) as second:
        auth(first, owner[1])
        auth(second, owner[1])
        broken["now"] = True
        assert (close_code(first), close_code(second)) == (1011, 1011)
    broken["now"] = False
    with connect(client, ticket_id) as again:  # новое соединение подписки
        auth(again, owner[1])


def error_logged_with_traceback(caplog: pytest.LogCaptureFixture) -> bool:
    return any(
        r.name == ticket_events.__name__ and r.levelno >= logging.ERROR and r.exc_info
        for r in caplog.records
    )


def test_redis_unavailable_at_subscribe_closes_1011(app, client, ticket_id, owner, caplog):
    dead = PubSubHub("redis://127.0.0.1:1/0", ping_seconds=1, queue_size=10)
    app.dependency_overrides[get_pubsub_hub] = lambda: dead
    with caplog.at_level(logging.ERROR), connect(client, ticket_id) as ws:
        ws.send_json({"type": "auth", "access_token": owner[1]})
        assert close_code(ws) == 1011
    assert error_logged_with_traceback(caplog)


def test_db_failure_in_access_check_closes_1011(client, ticket_id, owner, monkeypatch, caplog):
    def broken(*_: Any) -> None:
        raise OperationalError("SELECT 1", {}, Exception("нет связи"))

    monkeypatch.setattr(ticket_events, "_check_access", broken)
    with caplog.at_level(logging.ERROR), connect(client, ticket_id) as ws:
        ws.send_json({"type": "auth", "access_token": owner[1]})
        assert close_code(ws) == 1011
    assert error_logged_with_traceback(caplog)


def test_redis_failure_in_connect_limit_closes_1011(client, ticket_id, monkeypatch, caplog):
    def broken(*_: Any) -> None:
        raise RedisConnectionError("нет связи")

    monkeypatch.setattr(rate_limit, "hit", broken)
    with caplog.at_level(logging.ERROR), connect(client, ticket_id) as ws:
        assert close_code(ws) == 1011
    assert error_logged_with_traceback(caplog)


def test_render_failure_closes_1011_with_traceback(
    client, ticket_id, owner, real_redis, monkeypatch, caplog
):
    def broken(*_: Any) -> None:
        raise RuntimeError("сбой формирования кадра")

    monkeypatch.setattr(ticket_events, "_render", broken)
    with caplog.at_level(logging.ERROR), connect(client, ticket_id) as ws:
        auth(ws, owner[1])
        real_redis.publish(
            run_events(real_redis).channel(ticket_id), ticket_updated_payload(ticket_id)
        )
        assert close_code(ws) == 1011
    assert error_logged_with_traceback(caplog)
