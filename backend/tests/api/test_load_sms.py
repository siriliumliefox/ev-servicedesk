"""Мини-нагрузочный тест (Глава 10): 50 одновременных запросов SMS-кода без сбоев.

ASGI-приложение целиком (роутинг, пул потоков, реальный Redis), 50 разных номеров.
Лимит на IP поднят: в бою запросы идут с разных адресов, лимит проверяется отдельно.
Второй тест — тот же поток через адаптер A1 с его реальным лимитом 10 запросов/с.
"""

import asyncio
import time

import httpx
import pytest

from app.api.deps import get_sms_provider
from app.core.config import Settings, get_settings
from app.core.db import get_db
from app.core.redis import get_redis
from app.domain.auth.codes import CODE_PREFIX
from app.domain.auth.sms import A1SmsProvider
from app.main import create_app
from tests.api.conftest import API, api_settings

N = 50


async def fire(app, n: int = N) -> list[httpx.Response]:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as ac:
        return await asyncio.gather(
            *(
                ac.post(f"{API}/auth/phone/request-code", json={"phone": f"+3752970{i:05d}"})
                for i in range(n)
            )
        )


def load_settings(**overrides) -> Settings:
    return api_settings(sms_requests_per_ip_hour=N * 2, **overrides)


@pytest.fixture
def load_app(real_redis, sms):
    settings = load_settings()
    application = create_app(settings)
    application.dependency_overrides[get_settings] = lambda: settings
    application.dependency_overrides[get_redis] = lambda: real_redis
    application.dependency_overrides[get_sms_provider] = lambda: sms
    application.dependency_overrides[get_db] = lambda: None  # request-code не ходит в БД
    return application


def test_50_concurrent_sms_requests(load_app, real_redis, sms):
    started = time.monotonic()
    responses = asyncio.run(fire(load_app))
    elapsed = time.monotonic() - started
    statuses = [r.status_code for r in responses]
    assert statuses == [200] * N, statuses
    assert sms.sent_count == N
    assert len(real_redis.keys(CODE_PREFIX + "*")) == N
    print(f"\n50 запросов кода: {elapsed:.2f} с, ошибок 0")


def test_50_concurrent_sms_requests_through_a1_rate_limit(real_redis):
    """Адаптер A1 при 10 rps: все 50 запросов успешны, к провайдеру — не чаще 10 в секунду."""
    stamps: list[float] = []

    def handler(request: httpx.Request) -> httpx.Response:
        stamps.append(time.monotonic())
        return httpx.Response(200, json={"status": True, "message_id": len(stamps)})

    settings = load_settings(
        sms_provider="a1", sms_provider_user="375290000000", sms_provider_api_key="k"
    )
    provider = A1SmsProvider(settings, client=httpx.Client(transport=httpx.MockTransport(handler)))
    application = create_app(settings)
    application.dependency_overrides[get_settings] = lambda: settings
    application.dependency_overrides[get_redis] = lambda: real_redis
    application.dependency_overrides[get_sms_provider] = lambda: provider

    started = time.monotonic()
    responses = asyncio.run(fire(application))
    assert [r.status_code for r in responses] == [200] * N
    assert len(stamps) == N
    stamps.sort()
    # k-й запрос к провайдеру — не раньше k / 10 с от старта: не чаще 10 в секунду.
    for k, stamp in enumerate(stamps):
        assert stamp - started >= k / settings.sms_provider_rps - 1e-3
