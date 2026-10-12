"""Клиент Redis: SMS-коды, счётчики rate limiting (ADR 0005) и события тикетов (ADR 0017)."""

import asyncio
import contextlib
import threading
from collections import Counter
from functools import lru_cache
from typing import Any

from redis import Redis
from redis.asyncio import Redis as AsyncRedis
from redis.exceptions import RedisError
from starlette.requests import HTTPConnection

from app.core.config import Settings, get_settings

SUBSCRIBE_TIMEOUT_SECONDS = 5.0  # ожидание подтверждения SUBSCRIBE


@lru_cache
def _client() -> Redis:
    return Redis.from_url(get_settings().redis_url, decode_responses=True)


def get_redis() -> Redis:
    """Зависимость FastAPI; в тестах подменяется (fakeredis или тестовая БД Redis)."""
    return _client()


# --- Общая подписка pub/sub (WebSocket событий тикета) ---------------------------------------


class PubSubLinkError(RedisError):
    """Связь подписки с Redis потеряна: обрыв, нет ответа на PING, сбой SUBSCRIBE."""


class SlowSubscriberError(Exception):
    """Слушатель не успевает забирать сообщения: его очередь переполнена."""


class Listener:
    """Сообщения одного канала для одного получателя (WebSocket-подключения).

    Очередь ограничена: переполнение — SlowSubscriberError, а не рост памяти процесса.
    """

    def __init__(self, channel: str, queue_size: int) -> None:
        self.channel = channel
        self.link: _Link | None = None  # задаёт PubSubHub.subscribe
        self.subscribed = asyncio.Event()  # SUBSCRIBE подтверждён (или связь потеряна)
        self._queue: asyncio.Queue[str | None] = asyncio.Queue(queue_size)
        self._error: Exception | None = None

    def push(self, data: str) -> None:
        if self._error is not None:
            return
        try:
            self._queue.put_nowait(data)
        except asyncio.QueueFull:
            self.fail(SlowSubscriberError())

    def fail(self, error: Exception) -> None:
        if self._error is not None:
            return
        self._error = error
        self.subscribed.set()
        # Будит ожидающего get(); полная очередь его и так не держит.
        with contextlib.suppress(asyncio.QueueFull):
            self._queue.put_nowait(None)

    def raise_if_failed(self) -> None:
        if self._error is not None:
            raise self._error

    async def get(self, timeout: float) -> str | None:
        """Следующее сообщение; None — за `timeout` секунд ничего не пришло."""
        self.raise_if_failed()
        try:
            data = await asyncio.wait_for(self._queue.get(), timeout)
        except TimeoutError:
            return None
        if data is None:
            self.raise_if_failed()
        return data


class _Link:
    """Одно соединение pub/sub цикла событий: каналы слушателей, чтение и PING.

    Команды (SUBSCRIBE, UNSUBSCRIBE, PING) уходят по очереди из одной задачи — порядок
    подписок и отписок сохраняется; добавить и убрать слушателя можно синхронно, в т. ч.
    из `finally` отменённого обработчика. Последний слушатель закрывает соединение.
    """

    def __init__(self, hub: "PubSubHub") -> None:
        self._hub = hub
        self.loop = asyncio.get_running_loop()
        self._client = AsyncRedis.from_url(
            hub.url,
            decode_responses=True,
            socket_keepalive=True,
            socket_connect_timeout=SUBSCRIBE_TIMEOUT_SECONDS,
        )
        self._pubsub = self._client.pubsub()
        self._listeners: dict[str, set[Listener]] = {}
        self._confirmed: set[str] = set()
        # SUBSCRIBE без ответа по каналу: Redis отвечает по порядку, подтверждение — последний.
        self._unconfirmed: Counter[str] = Counter()
        self._commands: asyncio.Queue[tuple[str, ...]] = asyncio.Queue()
        self.closed = False
        self._task = asyncio.create_task(self._run())

    def add(self, listener: Listener) -> None:
        channel = listener.channel
        listeners = self._listeners.setdefault(channel, set())
        listeners.add(listener)
        if len(listeners) == 1:
            self._unconfirmed[channel] += 1
            self._commands.put_nowait(("SUBSCRIBE", channel))
        elif channel in self._confirmed:
            listener.subscribed.set()

    def remove(self, listener: Listener) -> None:
        listeners = self._listeners.get(listener.channel)
        if self.closed or listeners is None or listener not in listeners:
            return
        listeners.remove(listener)
        if listeners:
            return
        del self._listeners[listener.channel]
        self._confirmed.discard(listener.channel)
        if self._listeners:
            self._commands.put_nowait(("UNSUBSCRIBE", listener.channel))
        else:
            self.shutdown(None)

    def shutdown(self, error: BaseException | None) -> None:
        """Синхронно: ссылка больше не принимает слушателей, оставшиеся получают ошибку."""
        if self.closed:
            return
        self.closed = True
        self._hub._forget(self)
        for listeners in self._listeners.values():
            for listener in listeners:
                failure = PubSubLinkError("Связь подписки с Redis потеряна")
                failure.__cause__ = error
                listener.fail(failure)
        self._listeners.clear()
        if asyncio.current_task() is not self._task:
            self._task.cancel()

    async def wait_closed(self) -> None:
        with contextlib.suppress(asyncio.CancelledError):
            await self._task

    async def _run(self) -> None:
        sender: asyncio.Task[None] | None = None
        try:
            await self._pubsub.connect()
            sender = asyncio.create_task(self._send())
            await self._read()
        except asyncio.CancelledError:
            pass  # закрытие ссылки: последний слушатель ушёл или приложение остановлено
        except Exception as exc:  # обрыв, нет ответа на PING; причину пишет слушатель в лог
            self.shutdown(exc)
        finally:
            self.shutdown(None)
            if sender is not None:
                sender.cancel()
            with contextlib.suppress(RedisError, OSError):  # соединение могло уже оборваться
                await self._pubsub.aclose()
                await self._client.aclose()

    async def _send(self) -> None:
        try:
            while True:
                await self._pubsub.execute_command(*await self._commands.get())
        except Exception as exc:
            self.shutdown(exc)

    async def _read(self) -> None:
        """Сообщения → слушателям. В тишине — PING: полуоткрытое соединение не ждёт вечно."""
        heard = self.loop.time()
        pinged: float | None = None
        while True:
            interval = self._hub.ping_seconds
            message = await self._pubsub.get_message(timeout=interval)
            now = self.loop.time()
            if message is not None:
                heard, pinged = now, None
                self._dispatch(message)
            elif pinged is not None:
                if now - pinged >= interval:
                    raise PubSubLinkError("Redis не ответил на PING")
            elif now - heard >= interval:
                pinged = now
                self._commands.put_nowait(("PING",))

    def _dispatch(self, message: dict[str, Any]) -> None:
        kind, channel = message["type"], message["channel"]
        if kind == "message":
            for listener in tuple(self._listeners.get(channel, ())):
                listener.push(message["data"])
        elif kind == "subscribe":
            self._unconfirmed[channel] -= 1
            if self._unconfirmed[channel] > 0:
                return
            del self._unconfirmed[channel]
            if channel in self._listeners:
                self._confirmed.add(channel)
                for listener in self._listeners[channel]:
                    listener.subscribed.set()


class PubSubHub:
    """Общая подписка Redis pub/sub процесса (ADR 0017 п. 9).

    Одно соединение на цикл событий вместо соединения на WebSocket-подключение: каналы
    подписываются при первом слушателе процесса и отписываются при последнем. В uvicorn цикл
    один; Starlette TestClient без `with` даёт каждому подключению свой цикл — и свою ссылку.
    """

    def __init__(self, url: str, *, ping_seconds: float, queue_size: int) -> None:
        self.url = url
        self.ping_seconds = ping_seconds
        self.queue_size = queue_size
        self._links: dict[asyncio.AbstractEventLoop, _Link] = {}
        self._guard = threading.Lock()  # ссылки разных циклов создаются в разных потоках

    @classmethod
    def from_settings(cls, settings: Settings, url: str | None = None) -> "PubSubHub":
        return cls(
            url or settings.redis_url,
            ping_seconds=settings.redis_pubsub_ping_seconds,
            queue_size=settings.ws_event_queue_size,
        )

    async def subscribe(self, channel: str) -> Listener:
        """Слушатель канала после подтверждения SUBSCRIBE; иначе PubSubLinkError.

        Слушатель освобождается `unsubscribe` (синхронно — и из `finally` отменённой задачи).
        """
        listener = Listener(channel, self.queue_size)
        link = self._link()
        link.add(listener)
        try:
            try:
                await asyncio.wait_for(listener.subscribed.wait(), SUBSCRIBE_TIMEOUT_SECONDS)
            except TimeoutError as exc:
                raise PubSubLinkError("Нет подтверждения подписки") from exc
            listener.raise_if_failed()
        except BaseException:
            link.remove(listener)
            raise
        listener.link = link
        return listener

    def unsubscribe(self, listener: Listener) -> None:
        if listener.link is not None:
            listener.link.remove(listener)

    async def aclose(self) -> None:
        """Закрывает ссылку текущего цикла событий (остановка приложения)."""
        with self._guard:
            link = self._links.get(asyncio.get_running_loop())
        if link is not None:
            link.shutdown(PubSubLinkError("Приложение остановлено"))
            await link.wait_closed()

    def _link(self) -> _Link:
        loop = asyncio.get_running_loop()
        with self._guard:
            link = self._links.get(loop)
            if link is None:
                link = self._links[loop] = _Link(self)
            return link

    def _forget(self, link: _Link) -> None:
        with self._guard:
            if self._links.get(link.loop) is link:
                del self._links[link.loop]


def get_pubsub_hub(connection: HTTPConnection) -> PubSubHub:
    """Зависимость FastAPI: общая подписка процесса (создаётся в lifespan, app.main)."""
    return connection.app.state.pubsub_hub
