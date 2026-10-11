"""WebSocket событий тикета `/tickets/{ticketId}/ws` (ADR 0017 п. 9, docs/asyncapi.yaml).

Только доставка сервер → клиент. Первое сообщение клиента — `{"type": "auth",
"access_token": …}` не позже `ws_auth_timeout_seconds`, иначе закрытие 4401; токен в URL не
передаётся (URL попадают в логи прокси). Доступ — как у getTicket; нет доступа — 4403.
События приходят из Redis-канала `ticket:{id}` (несколько экземпляров backend); на каждом
событии пользователь и доступ к тикету проверяются заново: потерявший доступ при смене
исполнителя закрывается 4403, деактивированный — 4401. По истечении access-токена — 4401.

БД синхронная: обращения — в пуле потоков, каждое — в своей короткой сессии
(`get_session_scope`), чтобы долгоживущее подключение не держало соединение пула.
"""

import asyncio
import contextlib
import json
import logging
from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Path, WebSocket, WebSocketDisconnect
from redis.asyncio.client import PubSub
from starlette.concurrency import run_in_threadpool

from app.api.deps import PubSubRedisDep, SessionScopeDep, SettingsDep, StorageDep
from app.api.schemas.tickets import message_out, ticket_out
from app.core.config import Settings
from app.core.db import SessionScope
from app.core.errors import ApiError
from app.core.security import AccessClaims, InvalidTokenError, decode_access_token
from app.domain.tickets import access, events, service
from app.domain.tickets.attachments import Presign, presigner
from app.domain.tickets.events import EventType, TicketEvent

logger = logging.getLogger(__name__)

router = APIRouter()

CLOSE_UNAUTHORIZED = 4401  # нет/неверный auth, токен недействителен или истёк
CLOSE_FORBIDDEN = 4403  # тикета нет, он не виден или доступ потерян
CLOSE_INTERNAL = 1011
LISTEN_TIMEOUT_SECONDS = 30.0  # потолок ожидания события между проверками срока токена

Frame = dict[str, Any]


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
            data = ticket_out(ticket)
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
    pubsub: PubSub,
    scope: SessionScope,
    claims: AccessClaims,
    ticket_id: int,
    presign: Presign,
) -> int:
    """События канала → клиенту; возвращает код закрытия (истёк токен или нет доступа)."""
    while True:
        remaining = (claims.expires_at - datetime.now(UTC)).total_seconds()
        if remaining <= 0:
            return CLOSE_UNAUTHORIZED
        message = await pubsub.get_message(
            ignore_subscribe_messages=True, timeout=min(remaining, LISTEN_TIMEOUT_SECONDS)
        )
        if message is None:
            continue
        event = events.parse(message["data"])
        if event is None or event.ticket_id != ticket_id:
            continue
        outcome = await run_in_threadpool(_render, scope, claims.user_id, event, presign)
        if isinstance(outcome, int):
            return outcome
        if outcome is not None:
            await websocket.send_json(outcome)


async def _relay(
    websocket: WebSocket,
    pubsub: PubSub,
    scope: SessionScope,
    claims: AccessClaims,
    ticket_id: int,
    presign: Presign,
) -> int | None:
    """Доставка до закрытия: код закрытия сервером или None — клиент отключился сам."""
    forward = asyncio.create_task(_forward(websocket, pubsub, scope, claims, ticket_id, presign))
    drain = asyncio.create_task(_drain(websocket))
    try:
        await asyncio.wait({forward, drain}, return_when=asyncio.FIRST_COMPLETED)
    finally:
        for task in (forward, drain):
            task.cancel()
        await asyncio.gather(forward, drain, return_exceptions=True)
    if not forward.done() or forward.cancelled():
        return None
    if (exc := forward.exception()) is not None:
        if drain.done() and not drain.cancelled() and drain.exception() is None:
            return None  # клиент ушёл, отправка в закрытый сокет не удалась
        logger.error("Сбой доставки событий тикета: %s", type(exc).__name__)
        return CLOSE_INTERNAL
    return forward.result()


async def _close(websocket: WebSocket, code: int) -> None:
    # Клиент мог уже отключиться: закрывать нечего.
    with contextlib.suppress(RuntimeError, OSError, WebSocketDisconnect):
        await websocket.close(code)


@router.websocket("/tickets/{ticketId}/ws")
async def ticket_events(
    websocket: WebSocket,
    ticket_id: Annotated[int, Path(alias="ticketId")],
    scope: SessionScopeDep,
    settings: SettingsDep,
    storage: StorageDep,
    pubsub_redis: PubSubRedisDep,
) -> None:
    await websocket.accept()
    try:
        claims = await _authenticate(websocket, settings)
    except _Disconnected:
        return
    if claims is None:
        return await _close(websocket, CLOSE_UNAUTHORIZED)
    code = await run_in_threadpool(_check_access, scope, claims.user_id, ticket_id)
    if code is not None:
        return await _close(websocket, code)

    pubsub = pubsub_redis.pubsub()
    try:
        await pubsub.subscribe(events.channel(ticket_id))
        code = await _relay(
            websocket, pubsub, scope, claims, ticket_id, presigner(storage, settings)
        )
    finally:
        await pubsub.aclose()
    if code is not None:
        await _close(websocket, code)
