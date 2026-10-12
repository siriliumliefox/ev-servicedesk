"""Контракт docs/asyncapi.yaml ↔ docs/openapi.yaml (Глава 13, ADR 0017 п. 9).

Spectral (`npm run lint:asyncapi`) проверяет структуру AsyncAPI 3.0, но не примеры сообщений и не
payload в формате схем OpenAPI. Здесь: канал — путь тикета REST, payload событий — схемы
openapi.yaml по $ref, каждый пример валиден по своему payload, `type` конверта = имя сообщения;
коды закрытия и кадр `ready` сервера описаны в документе.
"""

from functools import cache
from pathlib import Path
from typing import Any

import pytest
import yaml
from jsonschema import Draft7Validator
from openapi_schema_validator import OAS30Validator

from app.api.routes import ticket_events

DOCS = Path(__file__).resolve().parents[3] / "docs"
OPENAPI_FORMAT = "application/vnd.oai.openapi;version=3.0.0"


@cache
def load(name: str) -> dict:
    return yaml.safe_load((DOCS / name).read_text(encoding="utf-8"))


def inline(node: Any, doc: str = "asyncapi.yaml") -> Any:
    """Разворачивает $ref (локальные и ./openapi.yaml#/…) в самостоятельную схему."""
    if isinstance(node, list):
        return [inline(v, doc) for v in node]
    if not isinstance(node, dict):
        return node
    if "$ref" in node:
        target, _, pointer = node["$ref"].partition("#")
        doc = target.removeprefix("./") or doc
        resolved = load(doc)
        for part in pointer.strip("/").split("/"):
            resolved = resolved[part]
        return inline(resolved, doc)
    return {k: inline(v, doc) for k, v in node.items()}


MESSAGES = sorted(load("asyncapi.yaml")["components"]["messages"])


def test_asyncapi_3_0() -> None:
    assert load("asyncapi.yaml")["asyncapi"].startswith("3.0.")


def test_channel_is_ticket_ws() -> None:
    channel = load("asyncapi.yaml")["channels"]["ticketEvents"]
    assert channel["address"] == "/tickets/{ticketId}/ws"
    assert set(channel["parameters"]) == {"ticketId"}
    assert "/tickets/{ticketId}" in load("openapi.yaml")["paths"]


def test_events_reuse_openapi_schemas() -> None:
    """Payload событий — те же схемы, что в REST (один сериализатор на backend)."""
    messages = load("asyncapi.yaml")["components"]["messages"]
    data = {
        name: messages[name]["payload"]["schema"]["properties"]["data"]["$ref"]
        for name in ("MessageCreated", "TicketUpdated")
    }
    assert data == {
        "MessageCreated": "./openapi.yaml#/components/schemas/TicketMessage",
        "TicketUpdated": "./openapi.yaml#/components/schemas/Ticket",
    }


@pytest.mark.parametrize("name", MESSAGES)
def test_examples_match_payload(name: str) -> None:
    message = inline(load("asyncapi.yaml")["components"]["messages"][name])
    payload = message["payload"]
    if payload.get("schemaFormat") == OPENAPI_FORMAT:
        validator, schema = OAS30Validator, payload["schema"]
    else:
        assert "schemaFormat" not in payload, payload["schemaFormat"]
        validator, schema = Draft7Validator, payload

    kind = schema["properties"]["type"]
    assert kind.get("enum", [kind.get("const")]) == [message["name"]]
    assert message.get("examples"), "нужен пример сообщения"
    for example in message["examples"]:
        validator(schema).validate(example["payload"])
        assert example["payload"]["type"] == message["name"]


def test_close_codes_documented() -> None:
    """Каждый код закрытия сервера — строка таблицы «Коды закрытия» канала."""
    description = load("asyncapi.yaml")["channels"]["ticketEvents"]["description"]
    codes = {
        value
        for name, value in vars(ticket_events).items()
        if name.startswith("CLOSE_") and isinstance(value, int)
    }
    assert codes == {4401, 4403, 4429, 1011, 1013}
    for code in codes:
        assert f"| `{code}` |" in description, code


def test_ready_frame_matches_contract() -> None:
    """Кадр `ready` сервера — сообщение Ready, отправляется операцией send."""
    doc = load("asyncapi.yaml")
    ready = inline(doc["components"]["messages"]["Ready"])
    Draft7Validator(ready["payload"]).validate(ticket_events.READY)
    sent = [
        message["$ref"]
        for operation in doc["operations"].values()
        if operation["action"] == "send"
        for message in operation["messages"]
    ]
    assert "#/channels/ticketEvents/messages/ready" in sent
