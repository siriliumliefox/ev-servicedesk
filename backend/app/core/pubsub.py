"""Общая подписка Redis pub/sub процесса — WebSocket событий тикета (ADR 0017 п. 9)."""

import asyncio
import contextlib
from collections import Counter
from typing import Any

from redis.asyncio import Redis as AsyncRedis
from redis.exceptions import RedisError
from starlette.requests import HTTPConnection

from app.core.config import Settings

SUBSCRIBE_TIMEOUT_SECONDS = 5.0  # ожидание подтверждения SUBSCRIBE


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
    """Одно соединение pub/sub: каналы слушателей, чтение и PING.

    Команды (SUBSCRIBE, UNSUBSCRIBE, PING) уходят по очереди из одной задачи — порядок
    подписок и отписок сохраняется; добавить и убрать слушателя можно синхронно, в т. ч.
    из `finally` отменённого обработчика. Последний слушатель закрывает соединение.
    """

    def __init__(self, url: str, ping_seconds: float) -> None:
        self._ping_seconds = ping_seconds
        self._client = AsyncRedis.from_url(
            url,
            decode_responses=True,
            socket_keepalive=True,
            socket_connect_timeout=SUBSCRIBE_TIMEOUT_SECONDS,
        )
        self._pubsub = self._client.pubsub()
        self._listeners: dict[str, set[Listener]] = {}
        # SUBSCRIBE без ответа по каналу: Redis отвечает по порядку, подтверждение — последний.
        # Канал подтверждён, если у него есть слушатели и неподтверждённых SUBSCRIBE нет.
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
        elif not self._unconfirmed[channel]:
            listener.subscribed.set()

    def remove(self, listener: Listener) -> None:
        listeners = self._listeners.get(listener.channel)
        if self.closed or listeners is None or listener not in listeners:
            return
        listeners.remove(listener)
        if listeners:
            return
        del self._listeners[listener.channel]
        if self._listeners:
            self._commands.put_nowait(("UNSUBSCRIBE", listener.channel))
        else:
            self.shutdown(None)

    def shutdown(self, error: BaseException | None) -> None:
        """Синхронно: ссылка больше не принимает слушателей, оставшиеся получают ошибку."""
        if self.closed:
            return
        self.closed = True
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
        loop = asyncio.get_running_loop()
        interval = self._ping_seconds
        heard = loop.time()
        pinged: float | None = None
        while True:
            message = await self._pubsub.get_message(timeout=interval)
            now = loop.time()
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
            for listener in self._listeners.get(channel, ()):
                listener.subscribed.set()


class PubSubHub:
    """Общая подписка Redis pub/sub процесса (ADR 0017 п. 9).

    Одно соединение на процесс вместо соединения на WebSocket-подключение: каналы
    подписываются при первом слушателе процесса и отписываются при последнем. Соединение
    открывается при первом слушателе в цикле событий приложения (uvicorn — один цикл на
    процесс); потерянное или закрытое последним слушателем заменяется новым.
    """

    def __init__(self, url: str, *, ping_seconds: float, queue_size: int) -> None:
        self.url = url
        self.ping_seconds = ping_seconds
        self.queue_size = queue_size
        self._current: _Link | None = None

    @classmethod
    def from_settings(cls, settings: Settings) -> "PubSubHub":
        return cls(
            settings.redis_url,
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
        return listener

    def unsubscribe(self, listener: Listener) -> None:
        # Слушатель потерянного соединения новому не принадлежит — remove его пропустит.
        if self._current is not None:
            self._current.remove(listener)

    async def aclose(self) -> None:
        """Закрывает соединение (остановка приложения)."""
        if self._current is not None:
            self._current.shutdown(PubSubLinkError("Приложение остановлено"))
            await self._current.wait_closed()

    def _link(self) -> _Link:
        if self._current is None or self._current.closed:
            self._current = _Link(self.url, self.ping_seconds)
        return self._current


def get_pubsub_hub(connection: HTTPConnection) -> PubSubHub:
    """Зависимость FastAPI: общая подписка процесса (создаётся в lifespan, app.main)."""
    return connection.app.state.pubsub_hub
