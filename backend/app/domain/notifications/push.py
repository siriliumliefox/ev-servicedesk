"""Отправка push через FCM (Глава 15, ADR 0019 п. 2, 9, 11).

`PushSender` — seam: FCM HTTP v1 (`FcmPushSender`) в staging/production с Firebase-проектом,
`FakePushSender` — в тестах, CI и локально. Отправитель только классифицирует ответ FCM;
повторы, отзыв токена и журнал доставки — забота вызывающего (`dispatch`).

Текст и данные push — без ПД (ADR 0019 п. 11): токен и текст уходят в FCM/APNs (США).
В лог не пишутся ни токены, ни тексты.
"""

import json
import logging
import threading
import time
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Protocol

import httpx
import jwt

from app.core.config import Settings

logger = logging.getLogger(__name__)

FCM_SCOPE = "https://www.googleapis.com/auth/firebase.messaging"
FCM_SEND_URL = "https://fcm.googleapis.com/v1/projects/{project_id}/messages:send"
TOKEN_REFRESH_MARGIN_SECONDS = 60

# Коды FCM, при которых токен больше не годится: отзываем (ADR 0019 п. 9).
INVALID_TOKEN_CODES = frozenset({"UNREGISTERED", "INVALID_ARGUMENT", "SENDER_ID_MISMATCH"})


class Outcome(StrEnum):
    SENT = "sent"  # FCM принял сообщение — «доставлено» (ADR 0019 п. 10)
    RETRY = "retry"  # временная ошибка: 429, 5xx, сеть, авторизация
    INVALID_TOKEN = "invalid_token"  # токен мёртв — отозвать
    FAILED = "failed"  # окончательная ошибка без вины токена


@dataclass(frozen=True)
class PushMessage:
    token: str
    title: str
    body: str
    data: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class PushResult:
    outcome: Outcome
    error_code: str | None = None


class PushSender(Protocol):
    def send(self, message: PushMessage) -> PushResult: ...


class FakePushSender:
    """Отправитель в памяти: всё «доставлено»; тесты задают исход для токена через `outcomes`."""

    def __init__(self) -> None:
        self.sent: list[PushMessage] = []
        self.outcomes: dict[str, PushResult] = {}
        self._lock = threading.Lock()

    def send(self, message: PushMessage) -> PushResult:
        with self._lock:
            result = self.outcomes.get(message.token, PushResult(Outcome.SENT))
            if result.outcome is Outcome.SENT:
                self.sent.append(message)
            return result

    def to(self, token: str) -> list[PushMessage]:
        return [m for m in self.sent if m.token == token]


class FcmCredentialsError(ValueError):
    """Ключ сервисного аккаунта не разобран (значение ключа в сообщение не попадает)."""


@dataclass(frozen=True)
class ServiceAccount:
    project_id: str
    client_email: str
    private_key: str
    token_uri: str

    @classmethod
    def from_json(cls, raw: str) -> "ServiceAccount":
        try:
            data = json.loads(raw)
            return cls(
                project_id=data["project_id"],
                client_email=data["client_email"],
                private_key=data["private_key"],
                token_uri=data.get("token_uri") or "https://oauth2.googleapis.com/token",
            )
        except (ValueError, KeyError, TypeError):
            # from None: исходная ошибка разбора может нести фрагмент ключа.
            raise FcmCredentialsError(
                "FCM_SERVICE_ACCOUNT_JSON: нужен JSON-ключ сервисного аккаунта Firebase "
                "(project_id, client_email, private_key)"
            ) from None


class FcmPushSender:
    """FCM HTTP v1: OAuth-токен по JWT сервисного аккаунта (RS256), кэш до истечения."""

    def __init__(
        self, account: ServiceAccount, timeout: float, client: httpx.Client | None = None
    ) -> None:
        self._account = account
        self._client = client or httpx.Client(timeout=timeout)
        self._url = FCM_SEND_URL.format(project_id=account.project_id)
        self._lock = threading.Lock()
        self._access_token: str | None = None
        self._expires_at = 0.0

    def _token(self) -> str:
        with self._lock:
            if self._access_token and time.time() < self._expires_at:
                return self._access_token
            now = int(time.time())
            assertion = jwt.encode(
                {
                    "iss": self._account.client_email,
                    "scope": FCM_SCOPE,
                    "aud": self._account.token_uri,
                    "iat": now,
                    "exp": now + 3600,
                },
                self._account.private_key,
                algorithm="RS256",
            )
            response = self._client.post(
                self._account.token_uri,
                data={
                    "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
                    "assertion": assertion,
                },
            )
            response.raise_for_status()
            body = response.json()
            self._access_token = body["access_token"]
            lifetime = int(body.get("expires_in", 3600))
            self._expires_at = now + lifetime - TOKEN_REFRESH_MARGIN_SECONDS
            return self._access_token

    def _drop_token(self) -> None:
        with self._lock:
            self._access_token = None

    def send(self, message: PushMessage) -> PushResult:
        payload = {
            "message": {
                "token": message.token,
                "notification": {"title": message.title, "body": message.body},
                "data": message.data,
                "android": {"priority": "high"},
                "apns": {
                    "headers": {"apns-priority": "10"},
                    "payload": {"aps": {"sound": "default"}},
                },
            }
        }
        try:
            access_token = self._token()
            response = self._client.post(
                self._url, json=payload, headers={"Authorization": f"Bearer {access_token}"}
            )
        except (httpx.HTTPError, KeyError, ValueError) as exc:
            logger.warning("FCM недоступен: %s", type(exc).__name__)
            return PushResult(Outcome.RETRY, "NETWORK")
        if response.is_success:
            return PushResult(Outcome.SENT)
        code = _fcm_error_code(response)
        if response.status_code == 401:
            self._drop_token()  # истёк OAuth-токен или ошибка APNs — повторим с новым
        return classify(response.status_code, code)


def _fcm_error_code(response: httpx.Response) -> str:
    """errorCode из деталей FcmError, иначе status ошибки Google API, иначе HTTP-код."""
    try:
        error = response.json().get("error", {})
    except ValueError:
        return f"HTTP_{response.status_code}"
    for detail in error.get("details") or []:
        if isinstance(detail, dict) and detail.get("errorCode"):
            return str(detail["errorCode"])[:50]
    return str(error.get("status") or f"HTTP_{response.status_code}")[:50]


def classify(status_code: int, code: str) -> PushResult:
    if code in INVALID_TOKEN_CODES:
        return PushResult(Outcome.INVALID_TOKEN, code)
    if status_code in (401, 429) or status_code >= 500:
        return PushResult(Outcome.RETRY, code)
    return PushResult(Outcome.FAILED, code)


def get_push_sender(settings: Settings) -> PushSender:
    if settings.push_provider == "fcm":
        account = ServiceAccount.from_json(settings.fcm_service_account_json)
        return FcmPushSender(account, settings.fcm_timeout_seconds)
    return FakePushSender()
