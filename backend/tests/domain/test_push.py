"""FCM HTTP v1 (ADR 0019 п. 2, 9): OAuth сервисного аккаунта, разбор ошибок, настройки.

Сеть подменяется `httpx.MockTransport`; ключ сервисного аккаунта — одноразовый RSA.
"""

import json

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from pydantic import ValidationError

from app.core.config import Settings
from app.domain.notifications.push import (
    FCM_SCOPE,
    FakePushSender,
    FcmCredentialsError,
    FcmPushSender,
    Outcome,
    PushMessage,
    ServiceAccount,
    classify,
    get_push_sender,
)

TOKEN_URI = "https://oauth2.example.test/token"


@pytest.fixture(scope="module")
def key() -> rsa.RSAPrivateKey:
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


@pytest.fixture(scope="module")
def account_json(key: rsa.RSAPrivateKey) -> str:
    pem = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode()
    return json.dumps(
        {
            "type": "service_account",
            "project_id": "ev-test",
            "client_email": "push@ev-test.iam.gserviceaccount.com",
            "private_key": pem,
            "token_uri": TOKEN_URI,
        }
    )


class Fcm:
    """Поддельные OAuth и FCM: ответы FCM задаёт тест, запросы запоминаются."""

    def __init__(self, key: rsa.RSAPrivateKey) -> None:
        self.public = key.public_key()
        self.token_requests = 0
        self.sends: list[httpx.Request] = []
        self.responses: list[httpx.Response] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        if str(request.url) == TOKEN_URI:
            self.token_requests += 1
            form = dict(x.split("=", 1) for x in request.content.decode().split("&"))
            claims = jwt.decode(
                form["assertion"], self.public, algorithms=["RS256"], audience=TOKEN_URI
            )
            assert claims["scope"] == FCM_SCOPE
            return httpx.Response(
                200, json={"access_token": f"at-{self.token_requests}", "expires_in": 3600}
            )
        assert str(request.url) == "https://fcm.googleapis.com/v1/projects/ev-test/messages:send"
        self.sends.append(request)
        return self.responses.pop(0) if self.responses else httpx.Response(200, json={})


def sender(account_json: str, fcm: Fcm) -> FcmPushSender:
    client = httpx.Client(transport=httpx.MockTransport(fcm))
    return FcmPushSender(ServiceAccount.from_json(account_json), timeout=5, client=client)


MESSAGE = PushMessage("device-token", "Новости", "Текст", {"notification_id": "1", "type": "news"})


def fcm_error(status: int, code: str) -> httpx.Response:
    return httpx.Response(
        status,
        json={
            "error": {
                "code": status,
                "status": "NOT_FOUND" if status == 404 else "ERR",
                "details": [
                    {
                        "@type": "type.googleapis.com/google.firebase.fcm.v1.FcmError",
                        "errorCode": code,
                    }
                ],
            }
        },
    )


def test_send_uses_cached_oauth_token_and_v1_payload(account_json, key):
    fcm = Fcm(key)
    push = sender(account_json, fcm)
    assert push.send(MESSAGE).outcome is Outcome.SENT
    assert push.send(MESSAGE).outcome is Outcome.SENT
    assert fcm.token_requests == 1, "OAuth-токен кэшируется"
    request = fcm.sends[0]
    assert request.headers["Authorization"] == "Bearer at-1"
    body = json.loads(request.content)["message"]
    assert body["token"] == "device-token"
    assert body["notification"] == {"title": "Новости", "body": "Текст"}
    assert body["data"] == {"notification_id": "1", "type": "news"}
    assert body["apns"]["payload"]["aps"]["sound"] == "default"


@pytest.mark.parametrize(
    ("response", "outcome", "code"),
    [
        (fcm_error(404, "UNREGISTERED"), Outcome.INVALID_TOKEN, "UNREGISTERED"),
        (fcm_error(400, "INVALID_ARGUMENT"), Outcome.INVALID_TOKEN, "INVALID_ARGUMENT"),
        (fcm_error(403, "SENDER_ID_MISMATCH"), Outcome.INVALID_TOKEN, "SENDER_ID_MISMATCH"),
        (fcm_error(429, "QUOTA_EXCEEDED"), Outcome.RETRY, "QUOTA_EXCEEDED"),
        (fcm_error(503, "UNAVAILABLE"), Outcome.RETRY, "UNAVAILABLE"),
        (fcm_error(500, "INTERNAL"), Outcome.RETRY, "INTERNAL"),
        (fcm_error(401, "THIRD_PARTY_AUTH_ERROR"), Outcome.RETRY, "THIRD_PARTY_AUTH_ERROR"),
        (
            httpx.Response(403, json={"error": {"status": "PERMISSION_DENIED"}}),
            Outcome.FAILED,
            "PERMISSION_DENIED",
        ),
        (httpx.Response(502, text="<html>bad gateway</html>"), Outcome.RETRY, "HTTP_502"),
    ],
)
def test_fcm_errors_are_classified(account_json, key, response, outcome, code):
    fcm = Fcm(key)
    fcm.responses.append(response)
    result = sender(account_json, fcm).send(MESSAGE)
    assert (result.outcome, result.error_code) == (outcome, code)


def test_401_drops_cached_oauth_token(account_json, key):
    fcm = Fcm(key)
    push = sender(account_json, fcm)
    fcm.responses.append(httpx.Response(401, json={"error": {"status": "UNAUTHENTICATED"}}))
    assert push.send(MESSAGE).outcome is Outcome.RETRY
    assert push.send(MESSAGE).outcome is Outcome.SENT
    assert fcm.token_requests == 2
    assert fcm.sends[-1].headers["Authorization"] == "Bearer at-2"


def test_network_error_is_retry(account_json):
    def broken(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("нет сети", request=request)

    client = httpx.Client(transport=httpx.MockTransport(broken))
    push = FcmPushSender(ServiceAccount.from_json(account_json), timeout=5, client=client)
    result = push.send(MESSAGE)
    assert (result.outcome, result.error_code) == (Outcome.RETRY, "NETWORK")


def test_bad_service_account_does_not_leak_key():
    secret = '{"private_key": "-----BEGIN PRIVATE KEY-----SECRET'
    with pytest.raises(FcmCredentialsError) as info:
        ServiceAccount.from_json(secret)
    assert "SECRET" not in str(info.value) and info.value.__cause__ is None
    with pytest.raises(FcmCredentialsError):
        ServiceAccount.from_json('{"project_id": "x"}')


def test_classify_defaults():
    assert classify(400, "SOMETHING").outcome is Outcome.FAILED
    assert classify(500, "SOMETHING").outcome is Outcome.RETRY


def base(**overrides) -> dict:
    return {
        "environment": "staging",
        "jwt_secret": "j" * 40,
        "sms_code_secret": "s" * 40,
        "s3_access_key": "key",
        "s3_secret_key": "secret",
    } | overrides


def test_settings_require_fcm_key_and_real_push_in_production(account_json):
    with pytest.raises(ValidationError, match="FCM_SERVICE_ACCOUNT_JSON"):
        Settings(_env_file=None, **base(push_provider="fcm"))
    with pytest.raises(ValidationError, match="PUSH_PROVIDER=fake"):
        Settings(
            _env_file=None,
            **base(
                environment="production",
                sms_provider="a1",
                sms_provider_user="u",
                sms_provider_api_key="k",
            ),
        )
    staging = Settings(_env_file=None, **base())
    assert isinstance(get_push_sender(staging), FakePushSender), "staging без Firebase — фейк"
    fcm = Settings(
        _env_file=None, **base(push_provider="fcm", fcm_service_account_json=account_json)
    )
    assert isinstance(get_push_sender(fcm), FcmPushSender)


@pytest.mark.parametrize("body", [b"[1]", b'{"error": "invalid"}', b'{"error": {"details": "x"}}'])
def test_non_google_error_bodies_fall_back_to_http_code(account_json, key, body):
    fcm = Fcm(key)
    fcm.responses.append(httpx.Response(400, content=body))
    result = sender(account_json, fcm).send(MESSAGE)
    assert (result.outcome, result.error_code) == (Outcome.FAILED, "HTTP_400")


def test_broken_private_key_refused_at_start(account_json):
    data = json.loads(account_json)
    data["private_key"] = "-----BEGIN PRIVATE KEY-----\nAAAASECRET\n-----END PRIVATE KEY-----\n"
    with pytest.raises(FcmCredentialsError) as info:
        FcmPushSender(ServiceAccount.from_json(json.dumps(data)), timeout=5)
    assert "SECRET" not in str(info.value) and info.value.__cause__ is None
