"""SMS-провайдеры (ADR 0013): интерфейс, фейк для local/test и A1 «Smart-рассылка».

Текст SMS и код в логи не пишутся (ADR 0005); номер в логах маскируется.
"""

import logging
import threading
import time
from typing import Protocol

import httpx

from app.core.config import Settings

logger = logging.getLogger(__name__)


class SmsError(Exception):
    """SMS не отправлено. invalid_recipient — номер не принимается провайдером."""

    def __init__(self, message: str, *, invalid_recipient: bool = False) -> None:
        super().__init__(message)
        self.invalid_recipient = invalid_recipient


class SmsProvider(Protocol):
    def send(self, phone: str, text: str) -> None: ...


def mask_phone(phone: str) -> str:
    return phone[:4] + "*" * max(len(phone) - 6, 0) + phone[-2:]


class FakeSmsProvider:
    """Хранит последнее сообщение на номер в памяти процесса — для тестов и local."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.outbox: dict[str, str] = {}
        self.sent_count = 0

    def send(self, phone: str, text: str) -> None:
        with self._lock:
            self.outbox[phone] = text
            self.sent_count += 1

    def last_text(self, phone: str) -> str | None:
        with self._lock:
            return self.outbox.get(phone)


class _RateGate:
    """Не чаще rps запросов в секунду на процесс (лимит A1 — 10 запросов/с)."""

    def __init__(self, rps: float) -> None:
        self._interval = 1.0 / rps
        self._lock = threading.Lock()
        self._next = 0.0

    def wait(self) -> None:
        with self._lock:
            now = time.monotonic()
            slot = max(now, self._next)
            self._next = slot + self._interval
        delay = slot - now
        if delay > 0:
            time.sleep(delay)


# Коды ошибок A1 (apidoc 1.2.3): 7 — превышена частота запросов; 100–103 — получатель
# недопустим (невалидный номер, стоп-листы, запрещённый оператор).
A1_RATE_LIMITED = 7
A1_INVALID_RECIPIENT = {100, 101, 102, 103}


class A1SmsProvider:
    """A1 «Smart-рассылка», HTTP API v1.2.3: POST {url}/send/sms.

    Авторизация — user (msisdn) + apikey; параметры передаются в теле POST, чтобы ключ
    не попадал в URL и журналы прокси. Доступ разрешён только с IP, сообщённого A1.
    """

    def __init__(
        self, settings: Settings, client: httpx.Client | None = None, retries: int = 3
    ) -> None:
        self._settings = settings
        self._client = client or httpx.Client(timeout=10.0)
        self._gate = _RateGate(settings.sms_provider_rps)
        self._retries = retries

    def send(self, phone: str, text: str) -> None:
        data = {
            "user": self._settings.sms_provider_user,
            "apikey": self._settings.sms_provider_api_key,
            "msisdn": phone.removeprefix("+"),
            "text": text,
            "dlr_timeout": "10",
        }
        if self._settings.sms_sender:
            data["sender"] = self._settings.sms_sender
        url = self._settings.sms_provider_url.rstrip("/") + "/send/sms"

        for attempt in range(1, self._retries + 1):
            self._gate.wait()
            try:
                response = self._client.post(url, data=data)
                body = response.json()
            except (httpx.HTTPError, ValueError) as exc:
                logger.warning("A1 SMS: сбой запроса (%s), попытка %d", type(exc).__name__, attempt)
                if attempt == self._retries:
                    raise SmsError("SMS-провайдер недоступен") from exc
                time.sleep(0.2 * attempt)
                continue
            if body.get("status") is True:
                logger.info(
                    "A1 SMS отправлено на %s, id=%s", mask_phone(phone), body.get("message_id")
                )
                return
            error = body.get("error") or {}
            code = error.get("code")
            if code == A1_RATE_LIMITED and attempt < self._retries:
                time.sleep(0.2 * attempt)
                continue
            logger.warning("A1 SMS: ошибка %s на %s", code, mask_phone(phone))
            raise SmsError(
                f"SMS-провайдер вернул ошибку {code}",
                invalid_recipient=code in A1_INVALID_RECIPIENT,
            )
        raise SmsError("SMS-провайдер не ответил")


_fake_provider = FakeSmsProvider()
_a1_provider: A1SmsProvider | None = None
_a1_lock = threading.Lock()


def get_sms_provider_for(settings: Settings) -> SmsProvider:
    """Один экземпляр A1 на процесс — общий ограничитель частоты и пул соединений."""
    global _a1_provider
    if settings.sms_provider == "a1":
        with _a1_lock:
            if _a1_provider is None:
                _a1_provider = A1SmsProvider(settings)
            return _a1_provider
    return _fake_provider


def fake_provider() -> FakeSmsProvider:
    return _fake_provider
