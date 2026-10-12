"""Безопасность Tickets Service и Uploads (Глава 13, ADR 0017, RBAC-04): доступ, ПД, presigned URL.

- 401 — без токена, с поддельным, просроченным или refresh-токеном, с токеном неизвестного,
  деактивированного или анонимизированного пользователя: каждая операция тегов Tickets и
  Uploads и WebSocket событий (закрытие 4401);
- 403 — роль вне `x-required-roles` (таблица ролей — из docs/openapi.yaml); проверка роли
  идёт раньше поиска тикета: по ответу не узнать, существует ли id;
- object-level — чужой аккаунт, удалённое авто (ADR 0017, «Уточнения реализации»), очередь,
  свой и чужой тикет инженера, администратор; 404 невидимого тикета неотличим от 404
  несуществующего; id вне диапазона — 404/422, а не 500;
- ПД (п. 12): контакты сотрудника скрыты от клиента в REST и в кадрах WebSocket по роли
  получателя; описания, тексты, имена файлов и ключи объектов не попадают в логи;
- presigned URL (п. 10): file_url при чтении — presigned GET на 15 минут, подписанный для
  публичного адреса S3; ключ загрузки не содержит имени файла.

Токены — настоящие (Глава 10): клиент входит по SMS-коду, персонал — по паролю.
"""

import base64
import json
import logging
import re
import time
import urllib.request
import uuid
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import parse_qs, unquote, urlencode, urlsplit, urlunsplit

import anyio
import botocore.auth
import httpx
import jwt
import pytest
from botocore.config import Config as BotoConfig
from fastapi import FastAPI
from fastapi.testclient import TestClient
from redis import Redis
from sqlalchemy.orm import Session
from starlette.testclient import WebSocketTestSession
from starlette.websockets import WebSocketDisconnect

from app.core import storage as storage_module
from app.core.config import Settings
from app.core.security import create_access_token
from app.core.storage import (
    FakeObjectStorage,
    ObjectStorage,
    S3ObjectStorage,
    StorageUnavailable,
    get_storage,
)
from app.domain.tickets import events
from app.models import AppUser
from app.models.enums import UserRole
from tests.api.conftest import (
    API,
    ZEEKR_VIN,
    add_vehicle,
    api_settings,
    assert_contract,
    bearer,
    contract,
    contract_operation,
)
from tests.api.test_ticket_events import (
    RECEIVE_TIMEOUT,
    assert_frame,
    close_code,
    connect,
    receive,
    receive_event,
    wait_subscribers,
)

Headers = dict[str, str]

# ---------- Участники и тикеты ----------

OWNER, STRANGER, EX_OWNER = "owner", "stranger", "ex_owner"  # клиенты
ENGINEER, OTHER_ENGINEER, ADMIN = "engineer", "other_engineer", "admin"  # персонал
CLIENTS = (OWNER, STRANGER, EX_OWNER)
STAFF = {ENGINEER: UserRole.ENGINEER, OTHER_ENGINEER: UserRole.ENGINEER, ADMIN: UserRole.ADMIN}
PHONES = {
    OWNER: "+375296610001",
    STRANGER: "+375296610002",
    EX_OWNER: "+375296610003",
    ENGINEER: "+375296610004",
    OTHER_ENGINEER: "+375296610005",
    ADMIN: "+375296610006",
}
NEW_OWNER_PHONE = "+375296610007"
VINS = {OWNER: ZEEKR_VIN, STRANGER: "L6TZ0010000000002", EX_OWNER: "L6TZ0010000000003"}

# Тикеты на авто владельца: очередь (new без исполнителя), назначенный инженеру, назначенный
# другому инженеру; тикет бывшего владельца на удалённом (проданном) авто — у инженера.
QUEUE, ASSIGNED, OTHERS, DELETED_VEHICLE = "queue", "assigned", "others", "deleted_vehicle"

GHOST_ID = 10**9  # id, которого нет
OUT_OF_RANGE_IDS = (0, -1, 2**63, -(2**63) - 1, 2**64, 10**30)
NOT_INTEGER_IDS = ("abc", "1.5", "1e3", "0x1")

JPEG = b"\xff\xd8\xff\xe0" + b"0" * 64
MP4 = b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 64


@dataclass
class World:
    tokens: dict[str, str]  # участник → access-токен настоящего входа
    users: dict[str, AppUser]
    vehicles: dict[str, int]  # клиент → его авто (у EX_OWNER — удалённое)
    tickets: dict[str, int]
    assignees: dict[str, int | None]  # тикет → исполнитель
    refresh_token: str  # владельца

    def headers(self, actor: str) -> Headers:
        return bearer(self.tokens[actor])


@pytest.fixture
def settings() -> Settings:
    # Без auth-сообщения WebSocket закрывается быстрее, чем через 5 с по умолчанию.
    return api_settings(ws_auth_timeout_seconds=0.5)


@pytest.fixture
def world(client: TestClient, login_client, as_staff, make_ticket, db: Session) -> World:
    tokens: dict[str, str] = {}
    users: dict[str, AppUser] = {}
    refresh_token = ""
    for actor in CLIENTS:
        session = login_client(PHONES[actor])
        tokens[actor] = session["access_token"]
        users[actor] = db.get_one(AppUser, session["user"]["id"])
        if actor == OWNER:
            refresh_token = session["refresh_token"]
    for actor, role in STAFF.items():
        headers, user = as_staff(PHONES[actor], role)
        tokens[actor] = headers["Authorization"].removeprefix("Bearer ")
        users[actor] = user
    vehicles = {
        actor: add_vehicle(client, bearer(tokens[actor]), VINS[actor])["id"] for actor in CLIENTS
    }

    def create(actor: str) -> int:
        r = client.post(
            f"{API}/tickets",
            json={"vehicle_id": vehicles[actor], "category": "sim", "description": "Нет сети"},
            headers=bearer(tokens[actor]),
        )
        assert r.status_code == 201, r.text
        return r.json()["id"]

    tickets = {
        QUEUE: create(OWNER),
        ASSIGNED: make_ticket(vehicles[OWNER], users[ENGINEER]).id,
        OTHERS: make_ticket(vehicles[OWNER], users[OTHER_ENGINEER]).id,
        DELETED_VEHICLE: create(EX_OWNER),
    }
    # Бывший владелец успел пообщаться с инженером, затем удалил авто (продажа, ADR 0003).
    sold = tickets[DELETED_VEHICLE]
    r = client.post(f"{API}/tickets/{sold}/claim", headers=bearer(tokens[ENGINEER]))
    assert r.status_code == 200, r.text
    r = client.post(
        f"{API}/tickets/{sold}/messages",
        json={"body": "Продаю авто"},
        headers=bearer(tokens[EX_OWNER]),
    )
    assert r.status_code == 201, r.text
    r = client.delete(f"{API}/vehicles/{vehicles[EX_OWNER]}", headers=bearer(tokens[EX_OWNER]))
    assert r.status_code == 204, r.text

    assignees = {
        QUEUE: None,
        ASSIGNED: users[ENGINEER].id,
        OTHERS: users[OTHER_ENGINEER].id,
        DELETED_VEHICLE: users[ENGINEER].id,
    }
    return World(tokens, users, vehicles, tickets, assignees, refresh_token)


# ---------- Операции контракта ----------


@dataclass(frozen=True)
class Op:
    method: str
    path: str  # {tid} — id тикета
    body: Callable[[World, str | None], dict[str, Any]] | None = None


def _status_body(_: World, ticket: str | None) -> dict[str, Any]:
    # Очередь остаётся в «new» (запрос текущего статуса — 200 без изменений): иначе она
    # исчезнет у инженера. Прочие — допустимый переход, видимость не меняется.
    return {"status": "new" if ticket == QUEUE else "waiting_vendor"}


def _assign_body(world: World, ticket: str | None) -> dict[str, Any]:
    # Тот же исполнитель — назначение без изменений; видимость не меняется.
    return {"assigned_engineer_id": world.assignees.get(ticket) if ticket else None}


OPS: dict[str, Op] = {
    "listTickets": Op("GET", "/tickets"),
    "createTicket": Op(
        "POST",
        "/tickets",
        lambda w, _: {"vehicle_id": w.vehicles[OWNER], "category": "sim", "description": "x"},
    ),
    "createPresignedUpload": Op(
        "POST", "/uploads/presign", lambda w, _: {"file_name": "a.jpg", "file_type": "photo"}
    ),
    "getTicket": Op("GET", "/tickets/{tid}"),
    "updateTicketStatus": Op("PATCH", "/tickets/{tid}/status", _status_body),
    "claimTicket": Op("POST", "/tickets/{tid}/claim"),
    "assignTicket": Op("PATCH", "/tickets/{tid}/assign", _assign_body),
    "listTicketMessages": Op("GET", "/tickets/{tid}/messages"),
    "createTicketMessage": Op(
        "POST", "/tickets/{tid}/messages", lambda w, _: {"body": "Проверка доступа"}
    ),
}
TICKET_OPS = tuple(op_id for op_id, op in OPS.items() if "{tid}" in op.path)
ERROR_CODES = {401: "UNAUTHORIZED", 403: "FORBIDDEN", 404: "NOT_FOUND"}


def call(
    client: TestClient,
    world: World,
    op_id: str,
    headers: Headers,
    ticket: str = ASSIGNED,
    tid: int | str | None = None,
    params: dict[str, Any] | None = None,
) -> httpx.Response:
    """Операция контракта над тикетом мира (`ticket`) или над произвольным id (`tid`)."""
    op = OPS[op_id]
    key = ticket if tid is None else None
    path = op.path.format(tid=world.tickets[ticket] if tid is None else tid)
    body = op.body(world, key) if op.body else None
    return client.request(op.method, f"{API}{path}", json=body, headers=headers, params=params)


def test_ops_table_covers_tickets_and_uploads():
    tagged = {
        op["operationId"]
        for item in contract()["paths"].values()
        for op in item.values()
        if isinstance(op, dict) and {"Tickets", "Uploads"} & set(op.get("tags", []))
    }
    assert tagged == set(OPS)


# ---------- WebSocket ----------

OPEN = "open"  # подключение принято, событие тикета доставлено


def _poll(ws: WebSocketTestSession) -> dict[str, Any] | None:
    try:
        return ws._send_rx.receive_nowait()
    except anyio.WouldBlock:
        return None


def ws_outcome(client: TestClient, redis: Redis, ticket_id: int, token: str | None) -> int | str:
    """OPEN — подключение подписано и получает события тикета; иначе — код закрытия.

    token=None — сообщение auth не отправляется (сервер ждёт его ws_auth_timeout_seconds).
    Доступ проверяется до подписки: отказ — закрытие без подписки на канал.
    """
    channel = events.channel(ticket_id)
    with connect(client, ticket_id) as ws:
        if token is not None:
            ws.send_json({"type": "auth", "access_token": token})
        deadline = time.monotonic() + RECEIVE_TIMEOUT
        while time.monotonic() < deadline:
            message = ws.portal.call(_poll, ws)
            if message is not None:
                assert message["type"] == "websocket.close", message
                return message.get("code", 1000)
            if dict(redis.pubsub_numsub(channel)).get(channel, 0) >= 1:
                events.ticket_updated(redis, ticket_id)
                frame = receive_event(ws)
                assert frame["type"] == "ticket.updated", frame
                assert frame["data"]["id"] == ticket_id, frame
                return OPEN
            time.sleep(0.01)
    raise AssertionError(f"WebSocket тикета {ticket_id}: нет ни закрытия, ни подписки")


# ---------- 401: токен отсутствует, подделан, просрочен, пользователь недоступен ----------

REJECTED_TOKENS = (
    "missing",
    "garbage",
    "foreign_secret",
    "alg_none",
    "tampered_payload",
    "expired",
    "refresh_token",
    "unknown_user",
    "deactivated_client",
    "deactivated_admin",
    "anonymized_client",
)


def _segment(data: dict[str, Any]) -> str:
    raw = json.dumps(data, separators=(",", ":")).encode()
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def _claims(token: str) -> dict[str, Any]:
    return jwt.decode(token, options={"verify_signature": False})


def rejected_token(kind: str, world: World, settings: Settings, db: Session) -> str | None:
    """Токен, который сервер обязан отклонить; подделки — с правами администратора."""
    admin = world.users[ADMIN]
    if kind == "missing":
        return None
    if kind == "garbage":
        return "not-a-jwt"
    if kind == "foreign_secret":
        foreign = api_settings(jwt_secret="attacker-secret-" + "a" * 32)
        return create_access_token(admin.id, "admin", foreign)
    if kind == "alg_none":
        return jwt.encode(_claims(world.tokens[ADMIN]), None, algorithm="none")
    if kind == "tampered_payload":
        # Подпись настоящего токена клиента, в payload — администратор.
        header, _, signature = world.tokens[OWNER].split(".")
        claims = _claims(world.tokens[OWNER]) | {"sub": str(admin.id), "role": "admin"}
        return f"{header}.{_segment(claims)}.{signature}"
    if kind == "expired":
        issued = datetime.now(UTC) - timedelta(seconds=settings.access_token_ttl_seconds + 60)
        return create_access_token(admin.id, "admin", settings, now=issued)
    if kind == "refresh_token":
        return world.refresh_token
    if kind == "unknown_user":
        return create_access_token(GHOST_ID, "admin", settings)
    actor = ADMIN if kind == "deactivated_admin" else OWNER
    user = world.users[actor]
    if kind == "anonymized_client":
        user.anonymized_at = datetime.now(UTC)
    else:
        user.is_active = False
    db.commit()
    return world.tokens[actor]  # выдан до деактивации и ещё не истёк


@pytest.mark.parametrize("kind", REJECTED_TOKENS)
def test_rejected_token_is_401_everywhere(client, world, settings, db, real_redis, kind):
    token = rejected_token(kind, world, settings, db)
    headers = {} if token is None else bearer(token)
    for op_id in OPS:
        r = call(client, world, op_id, headers)
        assert r.status_code == 401, (op_id, r.text)
        assert_contract(r, op_id)
        assert r.json()["error"]["code"] == "UNAUTHORIZED", op_id
        assert r.headers["WWW-Authenticate"] == "Bearer", op_id
    assert ws_outcome(client, real_redis, world.tickets[ASSIGNED], token) == 4401


def test_ws_accepts_token_only_in_auth_message(client, world):
    """Токен в URL или заголовке рукопожатия не принимается: URL попадают в логи (п. 9)."""
    tid = world.tickets[ASSIGNED]
    token = world.tokens[OWNER]
    query = urlencode({"access_token": token, "token": token})
    with client.websocket_connect(f"{API}/tickets/{tid}/ws?{query}") as ws:
        assert close_code(ws) == 4401
    with client.websocket_connect(
        f"{API}/tickets/{tid}/ws", headers=bearer(token), subprotocols=[token]
    ) as ws:
        assert close_code(ws) == 4401


# ---------- 403: роль вне x-required-roles ----------

ACTOR_OF_ROLE = {"client": OWNER, "engineer": ENGINEER, "admin": ADMIN}


def test_role_outside_contract_roles_is_403(client, world):
    """Роли — из docs/openapi.yaml; чужая роль — 403 и для существующего, и для любого id."""
    for op_id in OPS:
        roles = set(contract_operation(op_id)[2]["x-required-roles"])
        for role, actor in ACTOR_OF_ROLE.items():
            headers = world.headers(actor)
            if role in roles:  # тикет ASSIGNED виден всем трём ролям
                r = call(client, world, op_id, headers)
                assert 200 <= r.status_code < 300, (op_id, role, r.text)
                assert_contract(r, op_id)
                continue
            targets: list[dict[str, Any]] = [{}]
            if op_id in TICKET_OPS:
                targets += [{"tid": GHOST_ID}, {"tid": 0}, {"tid": 2**63}]
            for target in targets:
                r = call(client, world, op_id, headers, **target)
                assert r.status_code == 403, (op_id, role, target, r.text)
                assert_contract(r, op_id)
                assert r.json()["error"]["code"] == "FORBIDDEN", (op_id, role, target)


# ---------- Object-level (RBAC-04) ----------

WS = "websocket"
# Порядок выполнения: чтение, затем запись. Записи не меняют видимость (см. _status_body,
# _assign_body); claim очереди инженером — последним (очередь становится его тикетом).
TICKET_ORDER = (ASSIGNED, OTHERS, DELETED_VEHICLE, QUEUE)
_NOBODY = {
    "getTicket": (404, 404, 404, 404),
    "listTicketMessages": (404, 404, 404, 404),
    WS: (4403, 4403, 4403, 4403),
    "createTicketMessage": (404, 404, 404, 404),
    "updateTicketStatus": (403, 403, 403, 403),
    "assignTicket": (403, 403, 403, 403),
    "claimTicket": (403, 403, 403, 403),
}
EXPECTED: dict[str, dict[str, tuple[int | str, ...]]] = {
    #               ASSIGNED  OTHERS  DELETED_VEHICLE  QUEUE
    OWNER: {
        "getTicket": (200, 200, 404, 200),
        "listTicketMessages": (200, 200, 404, 200),
        WS: (OPEN, OPEN, 4403, OPEN),
        "createTicketMessage": (201, 201, 404, 201),
        "updateTicketStatus": (403, 403, 403, 403),
        "assignTicket": (403, 403, 403, 403),
        "claimTicket": (403, 403, 403, 403),
    },
    STRANGER: _NOBODY,  # клиент другого аккаунта
    EX_OWNER: _NOBODY,  # его авто удалено: тикеты для него не существуют
    ENGINEER: {
        "getTicket": (200, 404, 200, 200),
        "listTicketMessages": (200, 404, 200, 200),
        WS: (OPEN, 4403, OPEN, OPEN),
        "createTicketMessage": (201, 404, 201, 403),
        "updateTicketStatus": (200, 404, 200, 403),
        "assignTicket": (403, 403, 403, 403),
        "claimTicket": (200, 409, 200, 200),
    },
    ADMIN: {
        "getTicket": (200, 200, 200, 200),
        "listTicketMessages": (200, 200, 200, 200),
        WS: (OPEN, OPEN, OPEN, OPEN),
        "createTicketMessage": (201, 201, 201, 201),
        "updateTicketStatus": (200, 200, 200, 200),
        "assignTicket": (200, 200, 200, 200),
        "claimTicket": (403, 403, 403, 403),
    },
}
LISTED = {
    OWNER: {QUEUE, ASSIGNED, OTHERS},
    STRANGER: set(),
    EX_OWNER: set(),
    ENGINEER: {QUEUE, ASSIGNED, DELETED_VEHICLE},
    ADMIN: {QUEUE, ASSIGNED, OTHERS, DELETED_VEHICLE},
}


def listed(client: TestClient, world: World, headers: Headers, **params: Any) -> set[str]:
    r = client.get(f"{API}/tickets", params=params, headers=headers)
    assert r.status_code == 200, r.text
    assert_contract(r, "listTickets")
    body = r.json()
    by_id = {tid: key for key, tid in world.tickets.items()}
    ids = [t["id"] for t in body["items"]]
    assert set(ids) <= set(by_id), "в списке — только тикеты этого теста"
    assert body["meta"]["total_items"] == len(ids), "счётчик не выдаёт невидимые тикеты"
    return {by_id[tid] for tid in ids}


@pytest.mark.parametrize("actor", list(EXPECTED))
def test_object_level_matrix(client, world, real_redis, actor):
    headers = world.headers(actor)
    mismatches: list[str] = []

    # Список: видимое множество; фильтры только сужают его.
    assert listed(client, world, headers) == LISTED[actor]
    for params in (
        {"assigned_engineer_id": world.users[OTHER_ENGINEER].id},
        {"assigned_engineer_id": world.users[ENGINEER].id},
        {"status": "new"},
        {"status": "in_progress"},
        {"overdue": False},
        {"category": "sim"},
    ):
        found = listed(client, world, headers, **params)
        assert found <= LISTED[actor], (params, found)

    for op_id, expected in EXPECTED[actor].items():
        for ticket, want in zip(TICKET_ORDER, expected, strict=True):
            if op_id == WS:
                got = ws_outcome(client, real_redis, world.tickets[ticket], world.tokens[actor])
            else:
                r = call(client, world, op_id, headers, ticket=ticket)
                assert_contract(r, op_id)
                got = r.status_code
                if got == want and want >= 400:
                    code = "TICKET_ALREADY_CLAIMED" if want == 409 else ERROR_CODES[want]
                    if r.json()["error"]["code"] != code:
                        mismatches.append(f"{op_id} {ticket}: код {r.json()['error']['code']}")
                if got == want == 404:
                    # Невидимый тикет неотличим от несуществующего (не раскрываем id).
                    ghost = call(client, world, op_id, headers, tid=GHOST_ID)
                    if ghost.json() != r.json():
                        mismatches.append(f"{op_id} {ticket}: 404 отличается от несуществующего")
            if got != want:
                mismatches.append(f"{op_id} {ticket}: {got}, ожидалось {want}")
    assert not mismatches, f"{actor}:\n" + "\n".join(mismatches)

    if actor == ENGINEER:  # claim очереди — последний запрос матрицы
        r = client.get(f"{API}/tickets/{world.tickets[QUEUE]}", headers=headers)
        assert r.json()["assigned_engineer_id"] == world.users[ENGINEER].id


def test_create_ticket_only_on_own_active_vehicle(client, world):
    def create(actor: str, vehicle_id: Any) -> httpx.Response:
        r = client.post(
            f"{API}/tickets",
            json={"vehicle_id": vehicle_id, "category": "sim", "description": "x"},
            headers=world.headers(actor),
        )
        assert_contract(r, "createTicket")
        return r

    assert create(OWNER, world.vehicles[OWNER]).status_code == 201
    ghost = create(OWNER, GHOST_ID)
    assert ghost.status_code == 404 and ghost.json()["error"]["code"] == "NOT_FOUND"
    for actor, vehicle_id in (
        (STRANGER, world.vehicles[OWNER]),  # чужое авто
        (OWNER, world.vehicles[EX_OWNER]),  # чужое удалённое
        (EX_OWNER, world.vehicles[EX_OWNER]),  # своё удалённое
        *((OWNER, vid) for vid in OUT_OF_RANGE_IDS),
    ):
        r = create(actor, vehicle_id)
        assert r.status_code == 404, (actor, vehicle_id, r.text)
        assert r.json() == ghost.json(), "чужое авто неотличимо от несуществующего"
    for vehicle_id in ("abc", 1.5, None):
        r = create(OWNER, vehicle_id)
        assert r.status_code == 422, (vehicle_id, r.text)
        assert r.json()["error"]["code"] == "VALIDATION_ERROR"


def test_sold_vehicle_tickets_hidden_from_ex_and_new_owner(client, world, login_client, real_redis):
    """Смена владельца — soft-delete (ADR 0003): переписка бывшего владельца не видна никому
    из клиентов; при восстановлении своего авто бывший владелец снова видит тикеты."""
    sold = world.tickets[DELETED_VEHICLE]
    new_owner = login_client(NEW_OWNER_PHONE)["access_token"]
    vehicle = add_vehicle(client, bearer(new_owner), VINS[EX_OWNER])
    assert vehicle["id"] != world.vehicles[EX_OWNER], "новый владелец — новая запись авто"

    for token in (new_owner, world.tokens[EX_OWNER]):
        assert listed(client, world, bearer(token)) == set()
        for op_id in ("getTicket", "listTicketMessages", "createTicketMessage"):
            r = call(client, world, op_id, bearer(token), ticket=DELETED_VEHICLE)
            assert r.status_code == 404, (op_id, r.text)
        assert ws_outcome(client, real_redis, sold, token) == 4403

    # Новый владелец снова продал авто; бывший вернул своё — история и тикеты на месте.
    r = client.delete(f"{API}/vehicles/{vehicle['id']}", headers=bearer(new_owner))
    assert r.status_code == 204
    restored = add_vehicle(client, world.headers(EX_OWNER), VINS[EX_OWNER])
    assert restored["id"] == world.vehicles[EX_OWNER]
    r = client.get(f"{API}/tickets/{sold}", headers=world.headers(EX_OWNER))
    assert r.status_code == 200, r.text
    assert ws_outcome(client, real_redis, sold, world.tokens[EX_OWNER]) == OPEN
    r = client.get(f"{API}/tickets/{sold}", headers=bearer(new_owner))
    assert r.status_code == 404


# ---------- id вне диапазона ----------


@pytest.mark.parametrize("op_id", TICKET_OPS)
def test_out_of_range_ticket_id_is_404_not_500(app, world, op_id):
    client = TestClient(app, raise_server_exceptions=False)
    headers = world.headers(ENGINEER if op_id == "claimTicket" else ADMIN)
    for tid in OUT_OF_RANGE_IDS:
        r = call(client, world, op_id, headers, tid=tid)
        assert r.status_code == 404, (tid, r.text)
        assert_contract(r, op_id)
        assert r.json()["error"]["code"] == "NOT_FOUND"
    # Не целое число — ошибка валидации пути. 422 объявлен не у всех операций (getTicket,
    # claimTicket), поэтому ответ с контрактом не сверяется: важно, что это не 500.
    for tid in NOT_INTEGER_IDS:
        r = call(client, world, op_id, headers, tid=tid)
        assert r.status_code == 422, (tid, r.text)
        assert r.json()["error"]["code"] == "VALIDATION_ERROR"


def test_ws_out_of_range_ticket_id(client, world, real_redis):
    for tid in (*OUT_OF_RANGE_IDS, GHOST_ID):
        assert ws_outcome(client, real_redis, tid, world.tokens[ADMIN]) == 4403, tid
    for tid in NOT_INTEGER_IDS:  # ошибка валидации пути — закрытие до accept
        with pytest.raises(WebSocketDisconnect) as info, connect(client, tid):
            pass
        assert info.value.code == 1008, tid


@pytest.mark.parametrize(
    ("op_id", "params"),
    [
        ("listTickets", {"assigned_engineer_id": 2**63}),
        ("listTickets", {"page": 0}),
        ("listTickets", {"page_size": 0}),
        ("listTickets", {"page_size": 101}),
        ("listTicketMessages", {"after_id": -1}),
        ("listTicketMessages", {"after_id": 2**63}),
        ("listTicketMessages", {"page": -1}),
        pytest.param(
            "listTickets",
            {"assigned_engineer_id": -(2**63) - 1},
            marks=pytest.mark.xfail(
                strict=True,
                reason="BUG: assigned_engineer_id без нижней границы — ниже BIGINT → 500",
            ),
        ),
        pytest.param(
            "listTickets",
            {"page": 2**62},
            marks=pytest.mark.xfail(
                strict=True, reason="BUG: page без верхней границы — OFFSET вне BIGINT → 500"
            ),
        ),
        pytest.param(
            "listTicketMessages",
            {"page": 2**63},
            marks=pytest.mark.xfail(
                strict=True, reason="BUG: page без верхней границы — OFFSET вне BIGINT → 500"
            ),
        ),
    ],
    ids=lambda v: v if isinstance(v, str) else ",".join(f"{k}={v[k]}" for k in v),
)
def test_out_of_range_query_is_not_500(app, world, op_id, params):
    """Параметр запроса вне диапазона — 422 или пустая страница, но не ошибка БД (500)."""
    client = TestClient(app, raise_server_exceptions=False)
    r = call(client, world, op_id, world.headers(ADMIN), params=params)
    assert r.status_code in (200, 422), r.text
    assert_contract(r, op_id)
    if r.status_code == 200:
        assert r.json()["items"] == []


# ---------- ПД: контакты сотрудника скрыты от клиента (п. 12) ----------


def give_contacts(client: TestClient, world: World, db: Session) -> dict[str, tuple[str, str]]:
    """Телефон и Telegram у всех авторов: клиент привязывает Telegram сам, персоналу — в БД."""
    contacts = {}
    for actor in (OWNER, ENGINEER, ADMIN):
        telegram_id = f"tg-{actor}-7731"
        if actor == OWNER:
            r = client.post(
                f"{API}/auth/telegram/link",
                json={"telegram_id": telegram_id},
                headers=world.headers(actor),
            )
            assert r.status_code == 200, r.text
        else:
            world.users[actor].telegram_id = telegram_id
        contacts[actor] = (PHONES[actor], telegram_id)
    db.commit()
    return contacts


def seen_contacts(viewer: str, author: str, contacts: dict) -> tuple[str | None, str | None]:
    """Телефон и Telegram автора глазами получателя: клиенту контакты сотрудника — null."""
    return (None, None) if viewer in CLIENTS and author in STAFF else contacts[author]


def test_rest_hides_staff_contacts_from_client(client, world, db):
    contacts = give_contacts(client, world, db)
    tid = world.tickets[ASSIGNED]
    authors = {}
    for author in (OWNER, ENGINEER, ADMIN):
        r = client.post(
            f"{API}/tickets/{tid}/messages",
            json={"body": f"Сообщение: {author}"},
            headers=world.headers(author),
        )
        assert r.status_code == 201, r.text
        me = r.json()["author"]
        assert (me["phone"], me["telegram_id"]) == contacts[author], "автор видит себя полностью"
        authors[r.json()["id"]] = author

    for viewer in (OWNER, ENGINEER, ADMIN):
        r = client.get(f"{API}/tickets/{tid}/messages", headers=world.headers(viewer))
        assert_contract(r, "listTicketMessages")
        items = r.json()["items"]
        assert {m["id"] for m in items} == set(authors)
        for m in items:
            author = authors[m["id"]]
            got = (m["author"]["phone"], m["author"]["telegram_id"])
            assert got == seen_contacts(viewer, author, contacts), (viewer, author)

    # Ни один ответ Tickets клиенту не содержит контактов персонала.
    for path in ("/tickets", f"/tickets/{tid}", f"/tickets/{tid}/messages"):
        text = client.get(f"{API}{path}", headers=world.headers(OWNER)).text
        for staff in (ENGINEER, ADMIN):
            assert not any(value in text for value in contacts[staff]), (path, staff)


def presigned_upload(
    client: TestClient, headers: Headers, file_name: str, file_type: str = "photo"
) -> dict[str, Any]:
    r = client.post(
        f"{API}/uploads/presign",
        json={"file_name": file_name, "file_type": file_type},
        headers=headers,
    )
    assert r.status_code == 200, r.text
    assert_contract(r, "createPresignedUpload")
    return r.json()


def test_ws_frames_hide_staff_contacts_per_recipient(
    client, world, db, real_redis, storage, settings
):
    contacts = give_contacts(client, world, db)
    tid = world.tickets[ASSIGNED]
    get_ttl = settings.presign_get_ttl_seconds
    with (
        connect(client, tid) as owner_ws,
        connect(client, tid) as engineer_ws,
        connect(client, tid) as admin_ws,
    ):
        sockets = {OWNER: owner_ws, ENGINEER: engineer_ws, ADMIN: admin_ws}
        for actor, ws in sockets.items():
            ws.send_json({"type": "auth", "access_token": world.tokens[actor]})
        wait_subscribers(real_redis, tid, len(sockets))

        for author in (OWNER, ENGINEER, ADMIN):
            body: dict[str, Any] = {"body": f"Сообщение: {author}"}
            if author != ADMIN:  # presign админу недоступен (x-required-roles)
                upload = presigned_upload(client, world.headers(author), "фото.jpg")
                storage.put(upload["file_url"], JPEG, "image/jpeg")
                body["attachments"] = [{"file_url": upload["file_url"], "file_type": "photo"}]
            r = client.post(
                f"{API}/tickets/{tid}/messages", json=body, headers=world.headers(author)
            )
            assert r.status_code == 201, r.text

            for viewer, ws in sockets.items():
                raw = receive(ws)["text"]
                data = assert_frame(json.loads(raw), "message.created", "TicketMessage")
                assert data["id"] == r.json()["id"]
                got = (data["author"]["phone"], data["author"]["telegram_id"])
                assert got == seen_contacts(viewer, author, contacts), (viewer, author)
                if viewer in CLIENTS and author in STAFF:
                    assert not any(value in raw for value in contacts[author]), (viewer, author)
                for attachment in data["attachments"]:  # presigned GET, не ключ загрузки
                    url = unquote(attachment["file_url"])
                    assert f"/tickets/{tid}/" in url and "/uploads/" not in url
                    assert "X-Fake-Method=GET" in url and f"X-Fake-Expires={get_ttl}" in url


# ---------- ПД: тексты, имена файлов и ключи объектов не пишутся в логи ----------

SECRET_DESCRIPTION = "Описание-ПД-q7z: Иванов Иван Иванович, ул. Тайная, 5"
SECRET_BODIES = {
    OWNER: "Текст-ПД-k3x: паспорт MP1234567",
    ENGINEER: "Ответ-ПД-w9v: перезвоните на +375291112233",
}
SECRET_FILES = {  # имя файла, тип вложения, MIME, содержимое
    OWNER: ("Паспорт-Иванова-q7z.jpg", "photo", "image/jpeg", JPEG),
    ENGINEER: ("Видео-Петрова-w9v.mp4", "video", "video/mp4", MP4),
}
SECRET_FRAGMENTS = ("Иванов", "Петрова", "MP1234567", "375291112233", "q7z", "k3x", "w9v")
# Транспорт S3 (botocore, urllib3) на DEBUG пишет URL запросов — с ключом объекта. Это
# отладка библиотек, а не журнал приложения: root-логгер по умолчанию — WARNING, приложение
# его не понижает.
S3_TRANSPORT_LOGGERS = ("botocore", "boto3", "urllib3", "s3transfer")
_FORMATTER = logging.Formatter("%(name)s %(levelname)s %(message)s")


def leaks(
    records: Iterable[logging.LogRecord], secrets: Iterable[str], skip: tuple[str, ...] = ()
) -> list[str]:
    """Секреты в записях лога: текст, шаблон, аргументы, трассировка и extra-поля."""
    found = []
    secrets = [s for s in secrets if s]
    for record in records:
        if record.name.startswith(skip):
            continue
        haystack = "\n".join(
            (_FORMATTER.format(record), repr(record.msg), repr(record.args), repr(vars(record)))
        )
        found += [f"{record.name} {record.levelname}: {s!r}" for s in secrets if s in haystack]
    return found


@pytest.fixture(params=["memory", "minio"])
def attachment_storage(request, app: FastAPI, storage: ObjectStorage) -> ObjectStorage:
    """Хранилище вложений: в памяти и настоящий S3 API (MinIO)."""
    if request.param == "memory":
        return storage
    s3 = request.getfixturevalue("s3_storage")
    app.dependency_overrides[get_storage] = lambda: s3
    return s3


def put_object(storage: ObjectStorage, upload: dict, data: bytes, mime: str) -> None:
    """Загрузка клиентом по presigned PUT."""
    if isinstance(storage, FakeObjectStorage):
        storage.put(upload["file_url"], data, mime)
        return
    # urllib, а не httpx: httpx сам пишет URL запроса (с ключом) в лог — это лог теста.
    request = urllib.request.Request(
        upload["upload_url"], data=data, method="PUT", headers={"Content-Type": mime}
    )
    with urllib.request.urlopen(request, timeout=10) as response:
        assert response.status == 200


def test_logs_have_no_texts_file_names_or_object_keys(client, world, attachment_storage, caplog):
    caplog.set_level(logging.DEBUG)
    uploaded: list[str] = []

    def attach(actor: str) -> dict[str, str]:
        file_name, file_type, mime, data = SECRET_FILES[actor]
        upload = presigned_upload(client, world.headers(actor), file_name, file_type)
        put_object(attachment_storage, upload, data, mime)
        uploaded.append(upload["file_url"])
        return {"file_url": upload["file_url"], "file_type": file_type}

    r = client.post(
        f"{API}/tickets",
        json={
            "vehicle_id": world.vehicles[OWNER],
            "category": "audio",
            "description": SECRET_DESCRIPTION,
            "attachments": [attach(OWNER)],
        },
        headers=world.headers(OWNER),
    )
    assert r.status_code == 201, r.text
    tid = r.json()["id"]
    r = client.post(f"{API}/tickets/{tid}/claim", headers=world.headers(ENGINEER))
    assert r.status_code == 200, r.text
    for actor in (OWNER, ENGINEER):
        r = client.post(
            f"{API}/tickets/{tid}/messages",
            json={"body": SECRET_BODIES[actor], "attachments": [attach(actor)]},
            headers=world.headers(actor),
        )
        assert r.status_code == 201, r.text
    for actor in (OWNER, ENGINEER, ADMIN):
        for path in ("/tickets", f"/tickets/{tid}", f"/tickets/{tid}/messages"):
            assert client.get(f"{API}{path}", headers=world.headers(actor)).status_code == 200
    # Отказы тоже не пишут присланное: повторная привязка и чужая загрузка.
    for file_url in (uploaded[0], uploaded[-1]):
        r = client.post(
            f"{API}/tickets/{tid}/messages",
            json={
                "body": SECRET_BODIES[OWNER],
                "attachments": [{"file_url": file_url, "file_type": "photo"}],
            },
            headers=world.headers(OWNER),
        )
        assert r.status_code == 422, r.text

    names = [key.rsplit("/", 1)[1] for key in uploaded]
    secrets = [
        SECRET_DESCRIPTION,
        *SECRET_BODIES.values(),
        *(file_name for file_name, *_ in SECRET_FILES.values()),
        *SECRET_FRAGMENTS,
        *uploaded,
        *(f"tickets/{tid}/{name}" for name in names),
        *names,
    ]
    skip = () if isinstance(attachment_storage, FakeObjectStorage) else S3_TRANSPORT_LOGGERS
    assert caplog.records, "логи перехватываются"
    assert not leaks(caplog.records, secrets, skip)


def test_failed_cleanup_is_logged_without_object_key(client, world, storage, monkeypatch, caplog):
    upload = presigned_upload(client, world.headers(OWNER), "Паспорт-Иванова-q7z.jpg")
    storage.put(upload["file_url"], JPEG, "image/jpeg")

    def failing_delete(key: str) -> None:
        raise StorageUnavailable(f"S3 delete_object: нет связи, {key}")

    monkeypatch.setattr(storage, "delete", failing_delete)
    caplog.set_level(logging.DEBUG)
    r = client.post(
        f"{API}/tickets",
        json={
            "vehicle_id": world.vehicles[OWNER],
            "category": "audio",
            "description": SECRET_DESCRIPTION,
            "attachments": [{"file_url": upload["file_url"], "file_type": "photo"}],
        },
        headers=world.headers(OWNER),
    )
    assert r.status_code == 201, "исходная загрузка останется до правила жизненного цикла"
    warned = [rec for rec in caplog.records if rec.name == "app.domain.tickets.attachments"]
    assert warned and warned[0].levelno == logging.WARNING
    name = upload["file_url"].rsplit("/", 1)[1]
    assert not leaks(caplog.records, [upload["file_url"], name, "Иванова", SECRET_DESCRIPTION])


@pytest.mark.xfail(
    strict=True,
    reason="BUG: 500 при недоступном S3 пишет в лог трассировку botocore с URL ключа объекта",
)
def test_s3_outage_error_log_has_no_object_key(app, world, storage, monkeypatch, caplog):
    client = TestClient(app, raise_server_exceptions=False)
    upload = presigned_upload(client, world.headers(OWNER), "Паспорт-Иванова-q7z.jpg")
    # Без повторных попыток botocore: тест не ждёт backoff; сбой тот же — нет соединения.
    no_retries = BotoConfig(retries={"max_attempts": 1, "mode": "standard"})
    monkeypatch.setattr(
        storage_module, "_BOTO_CONFIG", storage_module._BOTO_CONFIG.merge(no_retries)
    )
    down = S3ObjectStorage(
        endpoint="http://127.0.0.1:9",  # порт discard: соединение отклоняется
        bucket="ev-servicedesk-down-test",
        access_key="test-access",
        secret_key="test-secret",
        region="us-east-1",
    )
    app.dependency_overrides[get_storage] = lambda: down
    caplog.set_level(logging.WARNING)  # как в production: отладка библиотек не пишется
    r = client.post(
        f"{API}/tickets",
        json={
            "vehicle_id": world.vehicles[OWNER],
            "category": "audio",
            "description": "x",
            "attachments": [{"file_url": upload["file_url"], "file_type": "photo"}],
        },
        headers=world.headers(OWNER),
    )
    assert r.status_code == 500
    assert_contract(r, "createTicket")
    assert caplog.records, "сбой залогирован"
    name = upload["file_url"].rsplit("/", 1)[1]
    assert not leaks(caplog.records, [upload["file_url"], name])


# ---------- Presigned URL (п. 10) ----------

ALLOWED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".heic", ".heif", ".webp", ".mp4", ".mov"}
UPLOAD_KEY = re.compile(r"uploads/(\d+)/([0-9a-f-]{36})(\.[a-z0-9]+)?")
UPLOAD_NAMES = [  # имя файла, тип вложения, расширение ключа
    ("Паспорт Иванова И.И.JPG", "photo", ".jpg"),
    ("IMG_20260101_375291234567.jpeg", "photo", ".jpeg"),
    ("C:\\Users\\Ivanov\\Desktop\\права.png", "photo", ".png"),
    ("../../../etc/Петров/evil.webp", "photo", ".webp"),
    ("selfie.HEIC", "photo", ".heic"),
    ("Видео с регистратора.MOV", "video", ".mov"),
    ("dashcam.mp4", "video", ".mp4"),
    ("скан.jpg.exe", "photo", None),
    ("отчёт.pdf", "photo", None),
    ("clip.jpg", "video", None),
    (".jpg", "photo", None),
    ("без расширения", "photo", None),
    ("снимок.jpg ", "photo", None),
    ("имя%2F..%2Fsecret.png", "photo", ".png"),
    ("Сидоров_" + "я" * 240 + ".jpg", "photo", ".jpg"),
]


def test_upload_key_never_contains_file_name(client, world, settings):
    owner_id = world.users[OWNER].id
    keys = set()
    for file_name, file_type, extension in UPLOAD_NAMES:
        upload = presigned_upload(client, world.headers(OWNER), file_name, file_type)
        key = upload["file_url"]
        match = UPLOAD_KEY.fullmatch(key)
        assert match, (file_name, key)
        assert int(match.group(1)) == owner_id, "префикс — только свой user_id"
        assert uuid.UUID(match.group(2)).version == 4, "имя объекта — случайный UUID"
        assert match.group(3) == extension, file_name
        assert match.group(3) is None or match.group(3) in ALLOWED_EXTENSIONS
        keys.add(key)

        url = urlsplit(upload["upload_url"])
        assert unquote(url.path).endswith(f"/{key}")
        query = {k: v[0] for k, v in parse_qs(url.query).items()}
        assert query == {
            "X-Fake-Method": "PUT",
            "X-Fake-Expires": str(settings.presign_put_ttl_seconds),
        }
        # Ни одно слово имени не попадает ни в ключ, ни в URL загрузки (UUID исключён).
        rest = unquote(upload["upload_url"]).replace(match.group(2), "").lower()
        for word in re.findall(r"[^\W_]{3,}", file_name):
            if f".{word.lower()}" not in ALLOWED_EXTENSIONS:
                assert word.lower() not in rest, (file_name, word)
    assert len(keys) == len(UPLOAD_NAMES), "каждая загрузка — новый ключ"


PUBLIC_S3 = "https://files.ev-servicedesk.test"
SIGV4_PARAMS = {
    "X-Amz-Algorithm",
    "X-Amz-Credential",
    "X-Amz-Date",
    "X-Amz-Expires",
    "X-Amz-SignedHeaders",
    "X-Amz-Signature",
}


@pytest.fixture
def public_s3(s3_storage: S3ObjectStorage, s3_config: dict[str, str], app: FastAPI):
    """MinIO за публичным адресом: операции — на s3_config["endpoint"], подпись — для PUBLIC_S3."""
    public = S3ObjectStorage(**s3_config, public_endpoint=PUBLIC_S3)
    app.dependency_overrides[get_storage] = lambda: public
    return public


def assert_presigned(url: str, path: str, ttl: int) -> datetime:
    """Presigned URL SigV4 для публичного адреса S3 на `ttl` секунд; возвращает время подписи."""
    parts = urlsplit(url)
    assert f"{parts.scheme}://{parts.netloc}" == PUBLIC_S3, url
    assert unquote(parts.path) == path, url
    query = {k: v[0] for k, v in parse_qs(parts.query).items()}
    assert set(query) == SIGV4_PARAMS, url
    assert query["X-Amz-Algorithm"] == "AWS4-HMAC-SHA256"
    assert query["X-Amz-Expires"] == str(ttl)
    assert query["X-Amz-SignedHeaders"] == "host"
    assert query["X-Amz-Credential"].endswith("/s3/aws4_request")
    return datetime.strptime(query["X-Amz-Date"], "%Y%m%dT%H%M%SZ").replace(tzinfo=UTC)


def send(
    url: str, s3_config: dict[str, str], method: str = "GET", host: str | None = None, **kwargs
) -> httpx.Response:
    """Запрос по presigned URL к MinIO теста с заголовком Host публичного адреса.

    Подпись SigV4 включает Host: запрос принимается, только если URL подписан для этого
    адреса. host="" — без подмены (Host внутреннего адреса MinIO).
    """
    parts = urlsplit(url)
    internal = urlsplit(s3_config["endpoint"])
    target = urlunsplit((internal.scheme, internal.netloc, parts.path, parts.query, ""))
    headers = dict(kwargs.pop("headers", {}))
    if host != "":
        headers["Host"] = host or parts.netloc
    return httpx.request(method, target, headers=headers, timeout=10, **kwargs)


def with_query(url: str, **changes: str | None) -> str:
    parts = urlsplit(url)
    query = {k: v[0] for k, v in parse_qs(parts.query).items()} | changes
    query = {k: v for k, v in query.items() if v is not None}
    return urlunsplit(parts._replace(query=urlencode(query)))


def test_presigned_urls_signed_for_public_endpoint_and_expire(
    client, world, public_s3, s3_config, settings, real_redis, monkeypatch
):
    bucket = s3_config["bucket"]
    get_ttl, put_ttl = settings.presign_get_ttl_seconds, settings.presign_put_ttl_seconds
    assert get_ttl == put_ttl == 15 * 60, "ADR 0017 п. 10: 15 минут"
    now = datetime.now(UTC)

    # Загрузка: presigned PUT для публичного адреса; имени файла нет ни в ключе, ни в URL.
    photo = presigned_upload(client, world.headers(OWNER), "Паспорт Иванова 7731.JPG")
    signed_at = assert_presigned(photo["upload_url"], f"/{bucket}/{photo['file_url']}", put_ttl)
    assert abs(now - signed_at) < timedelta(minutes=2)
    assert "Иванова" not in unquote(photo["upload_url"]) and "7731" not in photo["upload_url"]
    jpeg = {"content": JPEG, "headers": {"Content-Type": "image/jpeg"}}
    r = send(photo["upload_url"], s3_config, "PUT", host="", **jpeg)
    assert r.status_code == 403, "подпись не для внутреннего адреса MinIO"
    r = send(photo["upload_url"], s3_config, "PUT", **jpeg)
    assert r.status_code == 200, r.text

    r = client.post(
        f"{API}/tickets",
        json={
            "vehicle_id": world.vehicles[OWNER],
            "category": "audio",
            "description": "Хрипит динамик",
            "attachments": [{"file_url": photo["file_url"], "file_type": "photo"}],
        },
        headers=world.headers(OWNER),
    )
    assert r.status_code == 201, r.text
    tid = r.json()["id"]
    photo_path = f"/{bucket}/tickets/{tid}/{photo['file_url'].rsplit('/', 1)[1]}"
    read_urls = [r.json()["attachments"][0]["file_url"]]
    r = client.post(f"{API}/tickets/{tid}/claim", headers=world.headers(ENGINEER))
    assert r.status_code == 200, r.text

    # Ответ инженера с видео — клиент получает его и по WebSocket.
    clip = presigned_upload(client, world.headers(ENGINEER), "diag.mp4", "video")
    r = send(
        clip["upload_url"], s3_config, "PUT", content=MP4, headers={"Content-Type": "video/mp4"}
    )
    assert r.status_code == 200, r.text
    clip_path = f"/{bucket}/tickets/{tid}/{clip['file_url'].rsplit('/', 1)[1]}"
    with connect(client, tid) as ws:
        ws.send_json({"type": "auth", "access_token": world.tokens[OWNER]})
        wait_subscribers(real_redis, tid, 1)
        r = client.post(
            f"{API}/tickets/{tid}/messages",
            json={
                "body": "Запись диагностики",
                "attachments": [{"file_url": clip["file_url"], "file_type": "video"}],
            },
            headers=world.headers(ENGINEER),
        )
        assert r.status_code == 201, r.text
        clip_urls = [r.json()["attachments"][0]["file_url"]]
        frame = assert_frame(receive_event(ws), "message.created", "TicketMessage")
        clip_urls.append(frame["attachments"][0]["file_url"])

    for actor in (OWNER, ENGINEER, ADMIN):
        r = client.get(f"{API}/tickets/{tid}", headers=world.headers(actor))
        assert_contract(r, "getTicket")
        read_urls.append(r.json()["attachments"][0]["file_url"])
        r = client.get(f"{API}/tickets/{tid}/messages", headers=world.headers(actor))
        assert_contract(r, "listTicketMessages")
        clip_urls += [a["file_url"] for m in r.json()["items"] for a in m["attachments"]]

    # Фото: ответ createTicket и карточка трём ролям; видео: ответ POST, кадр WebSocket и
    # история трём ролям.
    for urls, path, content, count in (
        (read_urls, photo_path, JPEG, 4),
        (clip_urls, clip_path, MP4, 5),
    ):
        assert len(urls) == count
        for url in urls:
            assert abs(now - assert_presigned(url, path, get_ttl)) < timedelta(minutes=2)
            got = send(url, s3_config)
            assert got.status_code == 200 and got.content == content, got.text

    url = read_urls[-1]
    assert send(url, s3_config, host="").status_code == 403, "подпись — для публичного адреса"
    assert send(url, s3_config, "PUT", content=b"x").status_code == 403, "GET не даёт записи"
    longer = with_query(url, **{"X-Amz-Expires": str(7 * 24 * 3600)})
    assert send(longer, s3_config).status_code == 403, "срок входит в подпись"
    unsigned = urlunsplit(urlsplit(url)._replace(query=""))
    assert send(unsigned, s3_config).status_code == 403, "публичного доступа к объектам нет"

    # Срок действия: URL, подписанный больше 15 минут назад, MinIO уже не принимает.
    # Подпись — локально (без запроса в S3), поэтому часы подписи сдвигаются только на чтение.
    signed_now = botocore.auth.get_current_datetime
    with monkeypatch.context() as m:
        m.setattr(
            botocore.auth,
            "get_current_datetime",
            lambda *a, **kw: signed_now(*a, **kw) - timedelta(seconds=get_ttl + 120),
        )
        r = client.get(f"{API}/tickets/{tid}", headers=world.headers(OWNER))
    stale = r.json()["attachments"][0]["file_url"]
    signed_at = assert_presigned(stale, photo_path, get_ttl)
    assert datetime.now(UTC) - signed_at > timedelta(seconds=get_ttl)
    expired = send(stale, s3_config)
    assert expired.status_code == 403 and "expired" in expired.text.lower(), expired.text
