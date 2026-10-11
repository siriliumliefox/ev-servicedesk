"""SMS-провайдеры (ADR 0013): интерфейс, фейк для local/test и A1 «Smart-рассылка».

Текст SMS и код в логи не пишутся (ADR 0005); номер в логах маскируется.
"""

import logging
import math
import threading
import time
from typing import Protocol

import httpx

from app.core.config import Settings

logger = logging.getLogger(__name__)


class SmsError(Exception):
    """SMS не отправлено.

    invalid_recipient — номер не принимается провайдером (→ 422);
    delivery_unknown — запрос мог дойти до провайдера (нет ответа): SMS могло уйти,
    поэтому код не аннулируется и повтор не делается — иначе платный дубль.
    """

    def __init__(
        self, message: str, *, invalid_recipient: bool = False, delivery_unknown: bool = False
    ) -> None:
        super().__init__(message)
        self.invalid_recipient = invalid_recipient
        self.delivery_unknown = delivery_unknown


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
    """Не чаще rps запросов в секунду на процесс (лимит A1 — 10 запросов/с).

    Слот выдаётся, только если ждать его не дольше max_wait: при перегрузке запрос
    сразу получает отказ, а не занимает поток на неопределённое время.
    """

    def __init__(self, rps: float, max_wait: float) -> None:
        self._interval = 1.0 / rps
        self._max_wait = max_wait
        self._lock = threading.Lock()
        self._next = 0.0

    def wait(self) -> None:
        with self._lock:
            now = time.monotonic()
            slot = max(now, self._next)
            if slot - now > self._max_wait:
                raise SmsError("Очередь SMS-провайдера переполнена")
            self._next = slot + self._interval
        delay = slot - now
        if delay > 0:
            time.sleep(delay)


# Коды ошибок A1 (apidoc 1.2.3).
A1_RATE_LIMITED = 7
A1_INVALID_RECIPIENT = {100, 101, 102, 103}
# Ошибки учётной записи и настройки — нужен человек, логируются как ERROR.
A1_ACCOUNT_ERRORS = {3, 4, 5, 6, 8, 104}
A1_DESCRIPTIONS = {
    1: "внутренняя ошибка A1",
    2: "некорректный API-вызов",
    3: "нет user или apikey",
    4: "неверный user или apikey",
    5: "IP сервера не разрешён в A1",
    6: "учётная запись не активирована",
    7: "превышена частота запросов",
    8: "канал доставки недоступен",
    100: "невалидный номер получателя",
    101: "номер в пользовательском стоп-листе",
    102: "номер в глобальном стоп-листе",
    103: "запрещённый оператор",
    104: "имя отправителя недоступно",
    105: "пустой текст",
    106: "стоп-слово в тексте",
}
# Запрос точно не дошёл до A1 — повтор безопасен.
_NOT_SENT_ERRORS = (httpx.ConnectError, httpx.ConnectTimeout, httpx.PoolTimeout)


def _error_code(body: dict) -> tuple[int | None, dict]:
    error = body.get("error")
    error = error if isinstance(error, dict) else {}
    try:
        return int(error.get("code")), error
    except (TypeError, ValueError):
        return None, error


class A1SmsProvider:
    """A1 «Smart-рассылка», HTTP API v1.2.3: POST {url}/send/sms.

    Авторизация — user (msisdn) + apikey; параметры передаются в теле POST, чтобы ключ
    не попадал в URL и журналы прокси (проверено на API 2026-10-11, ADR 0013).
    Доступ разрешён только с IP, сообщённого A1.
    """

    def __init__(
        self,
        settings: Settings,
        client: httpx.Client | None = None,
        retries: int = 2,
        max_queue_wait: float = 6.0,
    ) -> None:
        self._settings = settings
        self._client = client or httpx.Client(timeout=httpx.Timeout(5.0, connect=3.0))
        self._gate = _RateGate(settings.sms_provider_rps, max_queue_wait)
        self._retries = retries

    def _form(self, phone: str, text: str) -> dict[str, str]:
        # dlr_timeout — минуты (1…1440): SMS, не доставленное за время жизни кода, бесполезно.
        dlr_minutes = min(max(math.ceil(self._settings.sms_code_ttl_seconds / 60), 1), 1440)
        data = {
            "user": self._settings.sms_provider_user,
            "apikey": self._settings.sms_provider_api_key,
            "msisdn": phone.removeprefix("+"),
            "text": text,
            "dlr_timeout": str(dlr_minutes),
        }
        if self._settings.sms_sender:
            data["sender"] = self._settings.sms_sender
        return data

    def send(self, phone: str, text: str) -> None:
        data = self._form(phone, text)
        url = self._settings.sms_provider_url.rstrip("/") + "/send/sms"

        for attempt in range(1, self._retries + 1):
            self._gate.wait()
            try:
                response = self._client.post(url, data=data)
            except _NOT_SENT_ERRORS as exc:
                logger.warning(
                    "A1 SMS: нет соединения (%s), попытка %d", type(exc).__name__, attempt
                )
                if attempt == self._retries:
                    raise SmsError("SMS-провайдер недоступен") from exc
                time.sleep(0.2 * attempt)
                continue
            except httpx.HTTPError as exc:
                logger.warning("A1 SMS: нет ответа (%s), доставка неизвестна", type(exc).__name__)
                raise SmsError("SMS-провайдер не ответил", delivery_unknown=True) from exc

            try:
                body = response.json()
            except ValueError:
                body = None
            if not isinstance(body, dict):
                logger.warning("A1 SMS: неожиданный ответ, HTTP %s", response.status_code)
                raise SmsError("Неожиданный ответ SMS-провайдера", delivery_unknown=True)
            if body.get("status") is True:
                logger.info(
                    "A1 SMS отправлено на %s, id=%s", mask_phone(phone), body.get("message_id")
                )
                return

            code, error = _error_code(body)
            if code == A1_RATE_LIMITED and attempt < self._retries:
                time.sleep(0.2 * attempt)
                continue
            logger.log(
                logging.ERROR if code in A1_ACCOUNT_ERRORS else logging.WARNING,
                "A1 SMS: ошибка %s (%s; parameter=%s) на %s",
                code,
                A1_DESCRIPTIONS.get(code, error.get("description", "?")),
                error.get("parameter"),
                mask_phone(phone),
            )
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
