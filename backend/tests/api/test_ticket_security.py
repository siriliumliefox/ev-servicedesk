"""Доступ к Tickets Service и Uploads (Глава 13, ADR 0017, RBAC-04).

- 401 — без токена, с поддельным, просроченным или refresh-токеном, с токеном неизвестного,
  деактивированного или анонимизированного пользователя: каждая операция тегов Tickets и
  Uploads и WebSocket событий (закрытие 4401);
- 403 — роль вне `x-required-roles` (таблица ролей — из docs/openapi.yaml); проверка роли
  идёт раньше поиска тикета: по ответу не узнать, существует ли id;
- object-level — чужой аккаунт, удалённое авто (ADR 0017, «Уточнения реализации»), очередь,
  свой и чужой тикет инженера, администратор; 404 невидимого тикета неотличим от 404
  несуществующего; id вне диапазона — 404/422, а не 500.

ПД и presigned URL — tests/api/test_ticket_privacy.py; участники и тикеты —
tests/api/ticket_world.py.
"""

import base64
import json
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import urlencode

import httpx
import jwt
import pytest
from fastapi.testclient import TestClient
from redis import Redis
from sqlalchemy.orm import Session

from app.api.pagination import PAGE_MAX, PAGE_SIZE_MAX
from app.core.config import Settings
from app.core.security import create_access_token
from tests.api.conftest import (
    API,
    Headers,
    add_vehicle,
    api_settings,
    assert_contract,
    bearer,
    contract,
    contract_operation,
)
from tests.api.ticket_world import (
    ADMIN,
    ASSIGNED,
    DELETED_VEHICLE,
    ENGINEER,
    EX_OWNER,
    OTHER_ENGINEER,
    OTHERS,
    OWNER,
    QUEUE,
    STRANGER,
    VINS,
    World,
    build_world,
)
from tests.api.ticket_ws import (
    READY,
    RECEIVE_TIMEOUT,
    close_code,
    connect,
    poll,
    receive_event,
    run_events,
)

NEW_OWNER_PHONE = "+375296610007"
GHOST_ID = 10**9  # id, которого нет
OUT_OF_RANGE_IDS = (0, -1, 2**63, -(2**63) - 1, 2**64, 10**30)
NOT_INTEGER_IDS = ("abc", "1.5", "1e3", "0x1")


@pytest.fixture
def settings() -> Settings:
    # Без auth-сообщения WebSocket закрывается быстрее, чем через 5 с по умолчанию.
    return api_settings(ws_auth_timeout_seconds=0.5)


@pytest.fixture
def world(client: TestClient, login_client, as_staff, make_ticket, db: Session) -> World:
    return build_world(client, login_client, as_staff, make_ticket, db)


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


def ws_outcome(
    client: TestClient, redis: Redis, ticket_id: int | str, token: str | None
) -> int | str:
    """OPEN — подключение подписано и получает события тикета; иначе — код закрытия.

    token=None — сообщение auth не отправляется (сервер ждёт его ws_auth_timeout_seconds).
    Доступ проверяется до подписки: отказ — закрытие без кадра `ready`.
    """
    with connect(client, ticket_id) as ws:
        if token is not None:
            ws.send_json({"type": "auth", "access_token": token})
        deadline = time.monotonic() + RECEIVE_TIMEOUT
        while time.monotonic() < deadline:
            message = poll(ws)
            if message is None:
                time.sleep(0.01)
                continue
            if message["type"] == "websocket.close":
                return message.get("code", 1000)
            # Первый кадр открытого подключения — `ready`: подписка подтверждена Redis.
            assert json.loads(message["text"]) == READY, message
            run_events(redis).ticket_updated(ticket_id)
            frame = receive_event(ws)
            assert frame["type"] == "ticket.updated", frame
            assert frame["data"]["id"] == ticket_id, frame
            return OPEN
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
    for tid in NOT_INTEGER_IDS:  # не id тикета — как тикета нет (AsyncAPI: 4403)
        assert ws_outcome(client, real_redis, tid, world.tokens[ADMIN]) == 4403, tid


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
        ("listTickets", {"assigned_engineer_id": -(2**63) - 1}),
        # OFFSET = (page - 1) * page_size вне BIGINT.
        ("listTickets", {"page": 2**62}),
        ("listTickets", {"page": PAGE_MAX + 1}),
        ("listTicketMessages", {"page": 2**63}),
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


@pytest.mark.parametrize("op_id", ["listTickets", "listTicketMessages"])
def test_last_page_within_bigint_offset(app, world, op_id):
    """Наибольшая допустимая страница при наибольшем page_size — OFFSET в BIGINT: 200, пусто."""
    client = TestClient(app, raise_server_exceptions=False)
    params = {"page": PAGE_MAX, "page_size": PAGE_SIZE_MAX}
    r = call(client, world, op_id, world.headers(ADMIN), params=params)
    assert r.status_code == 200, r.text
    assert_contract(r, op_id)
    assert r.json()["items"] == [] and r.json()["meta"]["page"] == PAGE_MAX
