"""Unit: адаптер A1 «Smart-рассылка» (HTTP API 1.2.3) на подменённом транспорте httpx."""

import threading
import time
from urllib.parse import parse_qs

import httpx
import pytest

from app.core.config import Settings
from app.domain.auth.sms import A1SmsProvider, SmsError, mask_phone

SETTINGS = Settings(
    environment="test",
    sms_provider="a1",
    sms_provider_user="375290000000",
    sms_provider_api_key="test-api-key",
    sms_sender="ETSAUTO",
    sms_provider_rps=1000,
)


def provider(handler, settings: Settings = SETTINGS, retries: int = 3) -> A1SmsProvider:
    client = httpx.Client(transport=httpx.MockTransport(handler))
    return A1SmsProvider(settings, client=client, retries=retries)


def ok(request: httpx.Request) -> httpx.Response:
    return httpx.Response(200, json={"status": True, "message_id": 1, "parts": 1})


def test_send_posts_form_without_key_in_url():
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return ok(request)

    provider(handler).send("+375291234567", "код 1234")
    (request,) = seen
    assert request.method == "POST"
    assert str(request.url) == "https://smart-sender.a1.by/api/send/sms"
    assert "apikey" not in str(request.url)
    form = {k: v[0] for k, v in parse_qs(request.content.decode()).items()}
    assert form["user"] == "375290000000"
    assert form["apikey"] == "test-api-key"
    assert form["msisdn"] == "375291234567"  # формат A1: без «+»
    assert form["text"] == "код 1234"
    assert form["sender"] == "ETSAUTO"


def test_retries_on_a1_rate_limit_error():
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        if len(calls) == 1:
            return httpx.Response(200, json={"status": False, "error": {"code": 7}})
        return ok(request)

    provider(handler).send("+375291234567", "t")
    assert len(calls) == 2


def test_invalid_recipient_flagged():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, json={"status": False, "error": {"code": 100, "parameter": "msisdn"}}
        )

    with pytest.raises(SmsError) as exc:
        provider(handler).send("+375291234567", "t")
    assert exc.value.invalid_recipient is True


def test_auth_error_not_retried():
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        return httpx.Response(200, json={"status": False, "error": {"code": 4}})

    with pytest.raises(SmsError) as exc:
        provider(handler).send("+375291234567", "t")
    assert exc.value.invalid_recipient is False
    assert len(calls) == 1


def test_network_failure_retried_then_error():
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        raise httpx.ConnectError("down")

    with pytest.raises(SmsError):
        provider(handler, retries=2).send("+375291234567", "t")
    assert len(calls) == 2


def test_rate_gate_respects_rps_under_concurrency():
    """30 параллельных отправок при лимите 50 rps: k-й запрос — не раньше k × 20 мс от старта.

    Нижняя граница детерминирована (слоты выдаются последовательно), поэтому не зависит
    от дрожания планировщика потоков.
    """
    stamps: list[float] = []
    lock = threading.Lock()

    def handler(request: httpx.Request) -> httpx.Response:
        with lock:
            stamps.append(time.monotonic())
        return ok(request)

    settings = SETTINGS.model_copy(update={"sms_provider_rps": 50})
    p = provider(handler, settings)
    threads = [threading.Thread(target=p.send, args=("+375291234567", "t")) for _ in range(30)]
    started = time.monotonic()
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    stamps.sort()
    assert len(stamps) == 30
    for k, stamp in enumerate(stamps):
        assert stamp - started >= k * 0.02 - 1e-3


def test_mask_phone():
    assert mask_phone("+375291234567") == "+375*******67"
