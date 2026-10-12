"""Клиент WebSocket событий тикета для тестов (ADR 0017 п. 9, docs/asyncapi.yaml).

Подключение — Starlette TestClient. Его `receive` ждёт кадр бесконечно, поэтому чтение с
тайм-аутом и без ожидания идёт напрямую из очереди сессии (`_send_rx`, внутреннее поле
Starlette): к нему обращаются только `_receive_within` и `_receive_nowait` этого модуля.
"""

import json
from typing import Any

import anyio
import pytest
from fastapi.testclient import TestClient
from openapi_schema_validator import OAS30Validator
from redis import Redis
from starlette.testclient import WebSocketTestSession
from starlette.websockets import WebSocketDisconnect

from app.domain.tickets.events import TicketEvents
from tests.api.conftest import API, RUN_CHANNEL_PREFIX, _inline

RECEIVE_TIMEOUT = 5.0
READY = {"type": "ready"}

Message = dict[str, Any]


def connect(client: TestClient, ticket_id: int | str):
    return client.websocket_connect(f"{API}/tickets/{ticket_id}/ws")


async def _receive_within(ws: WebSocketTestSession, seconds: float) -> Message | None:
    with anyio.move_on_after(seconds):
        return await ws._send_rx.receive()
    return None


def _receive_nowait(ws: WebSocketTestSession) -> Message | None:
    try:
        return ws._send_rx.receive_nowait()
    except anyio.WouldBlock:
        return None


def receive(ws: WebSocketTestSession, timeout: float = RECEIVE_TIMEOUT) -> Message:
    """Кадр сервера с тайм-аутом; закрытие — WebSocketDisconnect с его кодом."""
    message = ws.portal.call(_receive_within, ws, timeout)
    if message is None:
        raise TimeoutError(f"нет кадра за {timeout} с")
    if message["type"] == "websocket.close":
        raise WebSocketDisconnect(message.get("code", 1000))
    return message


def poll(ws: WebSocketTestSession) -> Message | None:
    """Сообщение сервера (кадр или закрытие), если оно уже пришло; без ожидания."""
    return ws.portal.call(_receive_nowait, ws)


def assert_quiet(ws: WebSocketTestSession, seconds: float = 0.3, msg: str = "лишний кадр") -> None:
    """За `seconds` подключению ничего не пришло (ни кадра, ни закрытия)."""
    assert ws.portal.call(_receive_within, ws, seconds) is None, msg


def receive_event(ws: WebSocketTestSession) -> dict[str, Any]:
    """Следующий кадр события; служебный `ready` пропускается (его проверяет wait_ready)."""
    while (frame := json.loads(receive(ws)["text"])) == READY:
        pass
    return frame


def wait_ready(ws: WebSocketTestSession) -> None:
    """Кадр `ready`: подписка подтверждена Redis и доступ проверен — события не теряются."""
    assert json.loads(receive(ws)["text"]) == READY


def auth(ws: WebSocketTestSession, token: str) -> None:
    ws.send_json({"type": "auth", "access_token": token})
    wait_ready(ws)


def close_code(ws: WebSocketTestSession) -> int:
    with pytest.raises(WebSocketDisconnect) as info:
        receive(ws)
    return info.value.code


def schema(name: str) -> dict:
    return _inline({"$ref": f"#/components/schemas/{name}"})


def assert_frame(frame: dict, event_type: str, schema_name: str) -> dict:
    """Кадр события по docs/asyncapi.yaml: тип и `data` по схеме docs/openapi.yaml."""
    assert set(frame) == {"type", "data"} and frame["type"] == event_type
    OAS30Validator(schema(schema_name)).validate(frame["data"])
    return frame["data"]


def run_events(redis: Redis) -> TicketEvents:
    """События тикетов в каналах прогона — как у приложения с `api_settings`."""
    return TicketEvents(redis, RUN_CHANNEL_PREFIX)
