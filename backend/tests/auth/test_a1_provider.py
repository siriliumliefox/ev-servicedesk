"""Unit: адаптер A1 «Smart-рассылка» (HTTP API 1.2.3) на подменённом транспорте httpx."""

import logging
import threading
import time
from urllib.parse import parse_qs

import httpx
import pytest

from app.core.config import Settings
from app.domain.auth.sms import A1SmsProvider, SmsError, mask_phone

API_KEY = "test-api-key-123"
SETTINGS = Settings(
    _env_file=None,
    environment="test",
    sms_provider="a1",
    sms_provider_user="375290000000",
    sms_provider_api_key=API_KEY,
    sms_sender="ETSGOMEL",
)


def provider(handler, settings: Settings = SETTINGS, **kwargs) -> A1SmsProvider:
    client = httpx.Client(transport=httpx.MockTransport(handler))
    return A1SmsProvider(settings, client=client, **kwargs)


def ok(request: httpx.Request) -> httpx.Response:
    return httpx.Response(200, json={"status": True, "message_id": 1, "parts": 1})


def form_of(request: httpx.Request) -> dict[str, str]:
    return {k: v[0] for k, v in parse_qs(request.content.decode()).items()}


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
    form = form_of(request)
    assert form["user"] == "375290000000"
    assert form["apikey"] == API_KEY
    assert form["msisdn"] == "375291234567"  # формат A1: без «+»
    assert form["text"] == "код 1234"
    assert form["sender"] == "ETSGOMEL"
    # dlr_timeout — минуты: не дольше жизни кода (120 с → 2 мин).
    assert form["dlr_timeout"] == "2"


def test_retries_on_a1_rate_limit_error():
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        if len(calls) == 1:
            return httpx.Response(200, json={"status": False, "error": {"code": 7}})
        return ok(request)

    provider(handler).send("+375291234567", "t")
    assert len(calls) == 2


@pytest.mark.parametrize("code", [100, 101, 102, 103, "100"])
def test_invalid_recipient_flagged(code):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, json={"status": False, "error": {"code": code, "parameter": "msisdn"}}
        )

    with pytest.raises(SmsError) as exc:
        provider(handler).send("+375291234567", "t")
    assert exc.value.invalid_recipient is True
    assert exc.value.delivery_unknown is False


def test_account_error_not_retried_logged_without_key(caplog):
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        return httpx.Response(
            200, json={"status": False, "error": {"code": 5, "description": "IP"}}
        )

    with caplog.at_level(logging.INFO, logger="app.domain.auth.sms"):
        with pytest.raises(SmsError) as exc:
            provider(handler).send("+375291234567", "код 1234")
    assert exc.value.invalid_recipient is False and exc.value.delivery_unknown is False
    assert len(calls) == 1
    (record,) = (r for r in caplog.records if "ошибка" in r.getMessage())
    assert record.levelno == logging.ERROR
    message = record.getMessage()
    assert "IP сервера не разрешён" in message
    # В логе нет ключа, полного номера и текста SMS с кодом.
    assert API_KEY not in message and "375291234567" not in message and "1234" not in message


def test_connect_error_retried_then_error():
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        raise httpx.ConnectError("down")

    with pytest.raises(SmsError) as exc:
        provider(handler, retries=2).send("+375291234567", "t")
    assert len(calls) == 2
    assert exc.value.delivery_unknown is False  # точно не отправлено


def test_read_timeout_not_retried_delivery_unknown():
    """Запрос мог дойти до A1: повтор дал бы платный дубль."""
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        raise httpx.ReadTimeout("slow")

    with pytest.raises(SmsError) as exc:
        provider(handler, retries=3).send("+375291234567", "t")
    assert len(calls) == 1
    assert exc.value.delivery_unknown is True


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(200, json=[]),
        httpx.Response(200, json="x"),
        httpx.Response(502, text="<html>Bad Gateway</html>"),
    ],
    ids=["list", "string", "html-502"],
)
def test_unexpected_response_is_sms_error(response):
    with pytest.raises(SmsError) as exc:
        provider(lambda request: response).send("+375291234567", "t")
    assert exc.value.delivery_unknown is True


def test_malformed_error_object_is_sms_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"status": False, "error": "x"})

    with pytest.raises(SmsError) as exc:
        provider(handler).send("+375291234567", "t")
    assert exc.value.invalid_recipient is False


def test_rate_gate_respects_rps_under_concurrency():
    """12 параллельных отправок при лимите 10 rps: k-й запрос — не раньше k × 100 мс от старта.

    Нижняя граница детерминирована (слоты выдаются последовательно), поэтому не зависит
    от дрожания планировщика потоков.
    """
    stamps: list[float] = []
    lock = threading.Lock()

    def handler(request: httpx.Request) -> httpx.Response:
        with lock:
            stamps.append(time.monotonic())
        return ok(request)

    p = provider(handler)
    threads = [threading.Thread(target=p.send, args=("+375291234567", "t")) for _ in range(12)]
    started = time.monotonic()
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    stamps.sort()
    assert len(stamps) == 12
    for k, stamp in enumerate(stamps):
        assert stamp - started >= k * 0.1 - 1e-3


def test_rate_gate_rejects_when_queue_too_long():
    """Ожидание слота дольше max_queue_wait — сразу отказ, поток не занимается."""
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        return ok(request)

    p = provider(handler, max_queue_wait=0.05)
    p.send("+375291234567", "t")  # слот сейчас; следующий — через 100 мс
    with pytest.raises(SmsError) as exc:
        p.send("+375291234567", "t")
    assert exc.value.delivery_unknown is False
    assert len(calls) == 1


def test_mask_phone():
    assert mask_phone("+375291234567") == "+375*******67"
