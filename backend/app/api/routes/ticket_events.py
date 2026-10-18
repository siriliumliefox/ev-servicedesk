"""WebSocket событий тикета `/tickets/{ticketId}/ws` (ADR 0017 п. 9, docs/asyncapi.yaml).

Только доставка сервер → клиент. Первое сообщение клиента — `{"type": "auth",
"access_token": …}` не позже `ws_auth_timeout_seconds`, иначе закрытие 4401; токен в URL не
передаётся (URL попадают в логи прокси). Доступ — как у getTicket; нет доступа (и ticketId
не целое число) — 4403. После проверки доступа подключение подписывается на канал тикета
и присылает `{"type": "ready"}`: с этого момента события не теряются, клиент догружает
пропущенное через REST. События приходят из Redis pub/sub (несколько экземпляров backend)
через общую подписку процесса (`app.core.pubsub.PubSubHub`); на каждом событии пользователь
и доступ к тикету проверяются заново: потерявший доступ при смене исполнителя закрывается
4403, деактивированный — 4401. По истечении и при отзыве access-токена (выход, смена
пароля — ADR 0029 п. 12) — 4401.

Лимиты: попытки подключения с IP (`ws_connects_per_ip_minute`, Redis) и одновременные
подключения пользователя (`ws_max_sockets_per_user`, Redis — общий для всех процессов) — сверх
них 4429. Сбой Redis
или БД — 1011; не успевающий забирать события получатель — 1013.

Отказы — исключения домена (ApiError) и инфраструктуры; код закрытия выбирается в одном
месте, в обработчике `ticket_events`.

БД синхронная: обращения — в пуле потоков, каждое — в своей короткой сессии
(`get_session_scope`), чтобы долгоживущее подключение не держало соединение пула.
"""

import asyncio
import contextlib
import logging
import re
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Annotated, Any, Literal, NoReturn

from fastapi import APIRouter, Depends, Path, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field, StrictStr, ValidationError
from redis import Redis
from starlette.concurrency import run_in_threadpool

from app.api.deps import (
    PresignDep,
    RedisDep,
    SessionScopeDep,
    SettingsDep,
    TicketEventsDep,
    client_ip,
)
from app.api.schemas.tickets import Presign, TicketOut, message_out
from app.core import rate_limit
from app.core.config import Settings
from app.core.db import SessionScope
from app.core.errors import ApiError, rate_limited, unauthorized
from app.core.pubsub import Listener, PubSubHub, SlowSubscriberError, get_pubsub_hub
from app.core.security import AccessClaims, InvalidTokenError, decode_access_token
from app.domain.auth import revocation
from app.domain.tickets import access, service
from app.domain.tickets.events import MessageCreated, TicketEvents, TicketUpdated, parse

logger = logging.getLogger(__name__)

router = APIRouter()

CLOSE_UNAUTHORIZED = 4401  # нет/неверный auth, токен недействителен или истёк
CLOSE_FORBIDDEN = 4403  # тикета нет, он не виден, доступ потерян или ticketId не число
CLOSE_TOO_MANY = 4429  # лимит подключений пользователя или попыток с IP
CLOSE_INTERNAL = 1011  # сбой Redis или БД
CLOSE_TRY_AGAIN = 1013  # получатель не успевает забирать события
# Отказ домена → код закрытия; тикета нет и тикет не виден неразличимы, как 404 в REST.
_CLOSE_FOR_STATUS = {
    401: CLOSE_UNAUTHORIZED,
    403: CLOSE_FORBIDDEN,
    404: CLOSE_FORBIDDEN,
    429: CLOSE_TOO_MANY,
}
# Потолок ожидания события между проверками срока токена и активности пользователя:
# заблокированный администратором закрывается не позже чем через этот интервал (ADR 0021 п. 3).
LISTEN_TIMEOUT_SECONDS = 30.0
CONNECT_WINDOW_SECONDS = 60
# BIGINT без знака: прочее (`abc`, `1.5`, `-1`, цифры других алфавитов) — тикета нет.
_TICKET_ID = re.compile(r"[0-9]{1,19}")

Frame = dict[str, Any]
READY: Frame = {"type": "ready"}
PubSubHubDep = Annotated[PubSubHub, Depends(get_pubsub_hub)]

# Аренда места подключения пользователя в Redis (ADR 0028 п. 15): общий лимит для всех
# процессов uvicorn. Пока подключение живо, аренду продлевает фоновая задача.
SOCKET_LEASE_SECONDS = 90
SOCKET_RENEW_SECONDS = 30


@contextlib.asynccontextmanager
async def _user_socket(redis: Redis, user_id: int, limit: int) -> AsyncIterator[None]:
    """Место подключения пользователя на время блока; освобождается и при аварийном
    завершении (а если процесс упал — по истечении аренды)."""
    slot = rate_limit.Slot(redis, f"ws-user:{user_id}", uuid.uuid4().hex, SOCKET_LEASE_SECONDS)
    if not await run_in_threadpool(slot.acquire, limit):
        raise rate_limited(0, "Слишком много одновременных подключений")

    async def renew() -> NoReturn:
        while True:
            await asyncio.sleep(SOCKET_RENEW_SECONDS)
            await run_in_threadpool(slot.renew)

    renewing = asyncio.create_task(renew())
    try:
        yield
    finally:
        renewing.cancel()
        try:
            await asyncio.shield(run_in_threadpool(slot.release))
        except Exception:  # Redis недоступен: место освободит истечение аренды
            logger.warning("Место подключения не освобождено — истечёт по аренде")


def _ticket_id(raw: str) -> int:
    if not _TICKET_ID.fullmatch(raw):
        raise access.not_found()
    return int(raw)


class _AuthMessage(BaseModel, extra="forbid"):
    """AsyncAPI AuthMessage: только type и access_token."""

    type: Literal["auth"]
    access_token: StrictStr = Field(min_length=1)


def _check_token(redis: Redis, claims: AccessClaims) -> None:
    """Access-токен не отозван (выход, смена пароля, блокировка) — иначе 401."""
    if revocation.is_revoked(redis, claims):
        raise unauthorized("Сессия завершена — войдите заново")


async def _authenticate(websocket: WebSocket, settings: Settings, redis: Redis) -> AccessClaims:
    try:
        message = await asyncio.wait_for(websocket.receive(), settings.ws_auth_timeout_seconds)
    except TimeoutError as exc:
        raise unauthorized() from exc
    if message["type"] == "websocket.disconnect":
        raise WebSocketDisconnect(message.get("code", 1000))
    text = message.get("text")
    if text is None:  # бинарный кадр
        raise unauthorized()
    try:
        token = _AuthMessage.model_validate_json(text).access_token
        claims = decode_access_token(token, settings)
    except (ValidationError, InvalidTokenError) as exc:
        raise unauthorized() from exc
    await run_in_threadpool(_check_token, redis, claims)
    return claims


def _check_user(scope: SessionScope, user_id: int) -> None:
    """Пользователь по-прежнему доступен (иначе 401) — проверка в паузе между событиями."""
    with scope() as db:
        access.subscriber(db, user_id)


def _check_access(scope: SessionScope, user_id: int, ticket_id: int) -> None:
    """Пользователь доступен (иначе 401) и тикет ему виден (иначе 404)."""
    with scope() as db:
        access.ensure_visible(db, access.subscriber(db, user_id), ticket_id)


def _render(
    scope: SessionScope, user_id: int, event: MessageCreated | TicketUpdated, presign: Presign
) -> Frame | None:
    """Кадр события для получателя (правила REST); None — пропустить (сообщения нет).

    Пользователь и доступ проверяются заново: недоступен — 401, тикет больше не виден — 404.
    """
    with scope() as db:
        user = access.subscriber(db, user_id)
        if isinstance(event, TicketUpdated):
            # Видимость и загрузка — один запрос (смена исполнителя — повод события).
            ticket = access.get_ticket(db, user, event.ticket_id, *service.TICKET_OUT)
            data = TicketOut.model_validate(ticket)
        else:
            access.ensure_visible(db, user, event.ticket_id)
            message = service.get_message(db, event.ticket_id, event.message_id)
            if message is None:
                return None
            data = message_out(message, user, presign)
        return {"type": event.type, "data": data.model_dump(mode="json")}


async def _drain(websocket: WebSocket) -> None:
    """Сообщения клиента после auth не обрабатываются; ждём только закрытия."""
    while (await websocket.receive())["type"] != "websocket.disconnect":
        pass


async def _forward(
    websocket: WebSocket,
    listener: Listener,
    scope: SessionScope,
    redis: Redis,
    claims: AccessClaims,
    ticket_id: int,
    presign: Presign,
) -> NoReturn:
    """`ready`, затем события канала → клиенту — до истечения токена или потери доступа."""
    await websocket.send_json(READY)
    while True:
        remaining = (claims.expires_at - datetime.now(UTC)).total_seconds()
        if remaining <= 0:
            raise unauthorized("Срок действия токена истёк")
        data = await listener.get(timeout=min(remaining, LISTEN_TIMEOUT_SECONDS))
        await run_in_threadpool(_check_token, redis, claims)
        if data is None:
            await run_in_threadpool(_check_user, scope, claims.user_id)
            continue
        event = parse(data)
        if event is None or event.ticket_id != ticket_id:
            continue
        frame = await run_in_threadpool(_render, scope, claims.user_id, event, presign)
        if frame is not None:
            await websocket.send_json(frame)


async def _relay(
    websocket: WebSocket,
    listener: Listener,
    scope: SessionScope,
    redis: Redis,
    claims: AccessClaims,
    ticket_id: int,
    presign: Presign,
) -> None:
    """Доставка до закрытия: возврат — клиент отключился сам, иначе исключение доставки."""
    forward = asyncio.create_task(
        _forward(websocket, listener, scope, redis, claims, ticket_id, presign)
    )
    drain = asyncio.create_task(_drain(websocket))
    try:
        await asyncio.wait({forward, drain}, return_when=asyncio.FIRST_COMPLETED)
    finally:
        for task in (forward, drain):
            task.cancel()
        # wait, а не gather: отмена самого обработчика (закрытие сервера, TestClient) выходит
        # своим CancelledError, а не исключением отменённой подзадачи без причины отмены.
        await asyncio.wait({forward, drain})
    if forward.cancelled():
        return
    if not drain.cancelled() and drain.exception() is None:
        return  # клиент ушёл, отправка в закрытый сокет не удалась
    forward.result()  # исключение доставки: код закрытия выбирает ticket_events


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
    presign: PresignDep,
    redis: RedisDep,
    events: TicketEventsDep,
    hub: PubSubHubDep,
) -> None:
    # ticketId — строка: не число закрывается 4403 по контракту, а не 1008 до accept.
    await websocket.accept()
    try:
        await _serve(websocket, ticket_ref, scope, settings, presign, redis, events, hub)
        return
    except WebSocketDisconnect:
        return  # клиент ушёл сам: закрывать нечего
    except ApiError as exc:
        code = _CLOSE_FOR_STATUS.get(exc.status_code, CLOSE_INTERNAL)
    except SlowSubscriberError:
        logger.warning("Получатель событий тикета не успевает: подключение закрыто")
        code = CLOSE_TRY_AGAIN
    except Exception:
        # Redis, БД, сбой формирования кадра. Трассировка без ПД: параметры SQL скрыты
        # (hide_parameters), тексты — не в сообщениях исключений.
        logger.error("Сбой подключения к событиям тикета", exc_info=True)
        code = CLOSE_INTERNAL
    await _close(websocket, code)


async def _serve(
    websocket: WebSocket,
    ticket_ref: str,
    scope: SessionScope,
    settings: Settings,
    presign: Presign,
    redis: Redis,
    events: TicketEvents,
    hub: PubSubHub,
) -> None:
    """Подключение от лимитов до конца доставки; отказ или закрытие сервером — исключение."""
    await run_in_threadpool(
        rate_limit.enforce,
        redis,
        f"ws-ip:{client_ip(websocket)}",
        CONNECT_WINDOW_SECONDS,
        settings.ws_connects_per_ip_minute,
        "Слишком много попыток подключения",
    )
    claims = await _authenticate(websocket, settings, redis)
    async with _user_socket(redis, claims.user_id, settings.ws_max_sockets_per_user):
        ticket_id = _ticket_id(ticket_ref)
        await run_in_threadpool(_check_access, scope, claims.user_id, ticket_id)
        # Доступ проверяется до подписки: отказ не трогает Redis. Потерю доступа между
        # проверкой и подпиской ловит проверка на следующем событии и REST после `ready`.
        listener = await hub.subscribe(events.channel(ticket_id))
        try:
            await _relay(websocket, listener, scope, redis, claims, ticket_id, presign)
        finally:
            hub.unsubscribe(listener)
