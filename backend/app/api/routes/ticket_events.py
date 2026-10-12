"""WebSocket событий тикета `/tickets/{ticketId}/ws` (ADR 0017 п. 9, docs/asyncapi.yaml).

Только доставка сервер → клиент. Первое сообщение клиента — `{"type": "auth",
"access_token": …}` не позже `ws_auth_timeout_seconds`, иначе закрытие 4401; токен в URL не
передаётся (URL попадают в логи прокси). Доступ — как у getTicket; нет доступа (и ticketId
не целое число) — 4403. После проверки доступа подключение подписывается на канал тикета
и присылает `{"type": "ready"}`: с этого момента события не теряются, клиент догружает
пропущенное через REST. События приходят из Redis pub/sub (несколько экземпляров backend)
через общую подписку процесса (`PubSubHub`); на каждом событии пользователь и доступ к
тикету проверяются заново: потерявший доступ при смене исполнителя закрывается 4403,
деактивированный — 4401. По истечении access-токена — 4401.

Лимиты: попытки подключения с IP (`ws_connects_per_ip_minute`, Redis) и одновременные
подключения пользователя в процессе (`ws_max_sockets_per_user`) — сверх них 4429. Сбой Redis
или БД — 1011; не успевающий забирать события получатель — 1013.

БД синхронная: обращения — в пуле потоков, каждое — в своей короткой сессии
(`get_session_scope`), чтобы долгоживущее подключение не держало соединение пула.
"""

import asyncio
import contextlib
import json
import logging
import re
import threading
from collections import Counter
from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Path, WebSocket, WebSocketDisconnect
from redis import Redis
from redis.exceptions import RedisError
from sqlalchemy.exc import SQLAlchemyError
from starlette.concurrency import run_in_threadpool

from app.api.deps import RedisDep, SessionScopeDep, SettingsDep, StorageDep, get_presign
from app.api.schemas.tickets import Presign, TicketOut, message_out
from app.core import rate_limit
from app.core.config import Settings
from app.core.db import SessionScope
from app.core.errors import ApiError
from app.core.redis import Listener, PubSubHub, SlowSubscriberError, get_pubsub_hub
from app.core.security import AccessClaims, InvalidTokenError, decode_access_token
from app.core.storage import ObjectStorage
from app.domain.tickets import access, events, service
from app.domain.tickets.events import EventType, TicketEvent

logger = logging.getLogger(__name__)

router = APIRouter()

CLOSE_UNAUTHORIZED = 4401  # нет/неверный auth, токен недействителен или истёк
CLOSE_FORBIDDEN = 4403  # тикета нет, он не виден, доступ потерян или ticketId не число
CLOSE_TOO_MANY = 4429  # лимит подключений пользователя или попыток с IP
CLOSE_INTERNAL = 1011  # сбой Redis или БД
CLOSE_TRY_AGAIN = 1013  # получатель не успевает забирать события
LISTEN_TIMEOUT_SECONDS = 30.0  # потолок ожидания события между проверками срока токена
CONNECT_WINDOW_SECONDS = 60
# BIGINT без знака: прочее (`abc`, `1.5`, `-1`, цифры других алфавитов) — тикета нет.
_TICKET_ID = re.compile(r"[0-9]{1,19}")

Frame = dict[str, Any]
READY: Frame = {"type": "ready"}
PubSubHubDep = Annotated[PubSubHub, Depends(get_pubsub_hub)]


class _UserSockets:
    """Открытые подключения пользователя в процессе (лимит `ws_max_sockets_per_user`).

    Счётчик в памяти процесса: освобождается и при аварийном завершении обработчика.
    Подключения Starlette TestClient живут в разных потоках — счётчик под блокировкой.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._open: Counter[int] = Counter()

    @contextlib.contextmanager
    def hold(self, user_id: int, limit: int) -> Iterator[bool]:
        with self._lock:
            allowed = self._open[user_id] < limit
            if allowed:
                self._open[user_id] += 1
        try:
            yield allowed
        finally:
            if allowed:
                with self._lock:
                    self._open[user_id] -= 1
                    if not self._open[user_id]:
                        del self._open[user_id]


_user_sockets = _UserSockets()


def _connect_allowed(redis: Redis, ip: str, settings: Settings) -> bool:
    attempt = rate_limit.hit(redis, f"ws-ip:{ip}", CONNECT_WINDOW_SECONDS)
    return not attempt.exceeded(settings.ws_connects_per_ip_minute)


def _client_ip(websocket: WebSocket) -> str:
    # Как app.api.deps.client_ip: за прокси нужен --forwarded-allow-ips (Глава 26).
    return websocket.client.host if websocket.client else "unknown"


def _ticket_id(raw: str) -> int | None:
    return int(raw) if _TICKET_ID.fullmatch(raw) else None


def _access_token(text: str | None) -> str | None:
    """Токен из сообщения auth (AsyncAPI AuthMessage: только type и access_token)."""
    if text is None:
        return None
    try:
        frame = json.loads(text)
    except ValueError:
        return None
    if not isinstance(frame, dict) or set(frame) != {"type", "access_token"}:
        return None
    token = frame["access_token"]
    if frame["type"] != "auth" or not isinstance(token, str) or not token:
        return None
    return token


class _Disconnected(Exception):
    """Клиент закрыл подключение — закрывать в ответ нечего."""


async def _authenticate(websocket: WebSocket, settings: Settings) -> AccessClaims | None:
    try:
        message = await asyncio.wait_for(websocket.receive(), settings.ws_auth_timeout_seconds)
    except TimeoutError:
        return None
    if message["type"] == "websocket.disconnect":
        raise _Disconnected
    token = _access_token(message.get("text"))
    if token is None:
        return None
    try:
        return decode_access_token(token, settings)
    except InvalidTokenError:
        return None


def _check_access(scope: SessionScope, user_id: int, ticket_id: int) -> int | None:
    """Код закрытия, если пользователь недоступен или тикет ему не виден; иначе None."""
    with scope() as db:
        user = access.active_user(db, user_id)
        if user is None:
            return CLOSE_UNAUTHORIZED
        return None if access.is_visible(db, user, ticket_id) else CLOSE_FORBIDDEN


def _render(
    scope: SessionScope, user_id: int, event: TicketEvent, presign: Presign
) -> Frame | int | None:
    """Кадр события для получателя (правила REST) или код закрытия; None — пропустить."""
    with scope() as db:
        user = access.active_user(db, user_id)
        if user is None:
            return CLOSE_UNAUTHORIZED
        if event.type is EventType.TICKET_UPDATED:
            try:  # видимость и загрузка — один запрос (смена исполнителя — повод события)
                ticket = access.get_ticket(db, user, event.ticket_id, *service.TICKET_OUT)
            except ApiError:
                return CLOSE_FORBIDDEN
            data = TicketOut.model_validate(ticket)
        else:
            if not access.is_visible(db, user, event.ticket_id):
                return CLOSE_FORBIDDEN
            message = service.get_message(db, event.ticket_id, event.message_id or 0)
            if message is None:
                return None
            data = message_out(message, user, presign)
        return {"type": event.type.value, "data": data.model_dump(mode="json")}


async def _drain(websocket: WebSocket) -> None:
    """Сообщения клиента после auth не обрабатываются; ждём только закрытия."""
    while (await websocket.receive())["type"] != "websocket.disconnect":
        pass


async def _forward(
    websocket: WebSocket,
    listener: Listener,
    scope: SessionScope,
    claims: AccessClaims,
    ticket_id: int,
    presign: Presign,
) -> int:
    """`ready`, затем события канала → клиенту; код закрытия (истёк токен или нет доступа)."""
    await websocket.send_json(READY)
    while True:
        remaining = (claims.expires_at - datetime.now(UTC)).total_seconds()
        if remaining <= 0:
            return CLOSE_UNAUTHORIZED
        data = await listener.get(timeout=min(remaining, LISTEN_TIMEOUT_SECONDS))
        if data is None:
            continue
        event = events.parse(data)
        if event is None or event.ticket_id != ticket_id:
            continue
        outcome = await run_in_threadpool(_render, scope, claims.user_id, event, presign)
        if isinstance(outcome, int):
            return outcome
        if outcome is not None:
            await websocket.send_json(outcome)


async def _relay(
    websocket: WebSocket,
    listener: Listener,
    scope: SessionScope,
    claims: AccessClaims,
    ticket_id: int,
    presign: Presign,
) -> int | None:
    """Доставка до закрытия: код закрытия сервером или None — клиент отключился сам."""
    forward = asyncio.create_task(_forward(websocket, listener, scope, claims, ticket_id, presign))
    drain = asyncio.create_task(_drain(websocket))
    try:
        await asyncio.wait({forward, drain}, return_when=asyncio.FIRST_COMPLETED)
    finally:
        for task in (forward, drain):
            task.cancel()
        # wait, а не gather: отмена самого обработчика (закрытие сервера, TestClient) выходит
        # своим CancelledError, а не исключением отменённой подзадачи без причины отмены.
        await asyncio.wait({forward, drain})
    if not forward.done() or forward.cancelled():
        return None
    if (exc := forward.exception()) is not None:
        if drain.done() and not drain.cancelled() and drain.exception() is None:
            return None  # клиент ушёл, отправка в закрытый сокет не удалась
        if isinstance(exc, SlowSubscriberError):
            logger.warning("Получатель событий тикета не успевает: подключение закрыто")
            return CLOSE_TRY_AGAIN
        # Трассировка без ПД: параметры SQL скрыты (hide_parameters), тексты — не в сообщениях.
        logger.error("Сбой доставки событий тикета", exc_info=exc)
        return CLOSE_INTERNAL
    return forward.result()


async def _close(websocket: WebSocket, code: int) -> None:
    # Клиент мог уже отключиться: закрывать нечего.
    with contextlib.suppress(RuntimeError, OSError, WebSocketDisconnect):
        await websocket.close(code)


@router.websocket("/tickets/{ticketId}/ws")
async def ticket_events(
    websocket: WebSocket,
    ticket_ref: Annotated[str, Path(alias="ticketId")],
    scope: SessionScopeDep,
    settings: SettingsDep,
    storage: StorageDep,
    redis: RedisDep,
    hub: PubSubHubDep,
) -> None:
    # ticketId — строка: не число закрывается 4403 по контракту, а не 1008 до accept.
    await websocket.accept()
    code = await _serve(websocket, ticket_ref, scope, settings, storage, redis, hub)
    if code is not None:
        await _close(websocket, code)


async def _serve(
    websocket: WebSocket,
    ticket_ref: str,
    scope: SessionScope,
    settings: Settings,
    storage: ObjectStorage,
    redis: Redis,
    hub: PubSubHub,
) -> int | None:
    """Подключение от лимитов до конца доставки: код закрытия или None — клиент ушёл сам."""
    try:
        allowed = await run_in_threadpool(_connect_allowed, redis, _client_ip(websocket), settings)
    except RedisError:
        logger.error("Лимит подключений к событиям тикета не проверен", exc_info=True)
        return CLOSE_INTERNAL
    if not allowed:
        return CLOSE_TOO_MANY
    try:
        claims = await _authenticate(websocket, settings)
    except _Disconnected:
        return None
    if claims is None:
        return CLOSE_UNAUTHORIZED

    with _user_sockets.hold(claims.user_id, settings.ws_max_sockets_per_user) as held:
        if not held:
            return CLOSE_TOO_MANY
        ticket_id = _ticket_id(ticket_ref)
        if ticket_id is None:
            return CLOSE_FORBIDDEN
        try:
            code = await run_in_threadpool(_check_access, scope, claims.user_id, ticket_id)
        except SQLAlchemyError:
            logger.error("Доступ к событиям тикета не проверен", exc_info=True)
            return CLOSE_INTERNAL
        if code is not None:
            return code

        # Доступ проверяется до подписки: отказ не трогает Redis. Потерю доступа между
        # проверкой и подпиской ловит проверка на следующем событии и REST после `ready`.
        try:
            listener = await hub.subscribe(events.channel(ticket_id))
        except RedisError:
            logger.error("Подписка на события тикета не удалась", exc_info=True)
            return CLOSE_INTERNAL
        try:
            presign = get_presign(storage, settings)
            return await _relay(websocket, listener, scope, claims, ticket_id, presign)
        finally:
            hub.unsubscribe(listener)
