"""Запросы Vehicle и Aggregates для API-тестов (#73, D13): одна реализация вместо копий."""

from datetime import date
from typing import Any

import httpx
from fastapi.testclient import TestClient

from tests.api.conftest import API, Headers


def post_replace(
    client: TestClient, headers: Headers, vid: int, code: str, **body: Any
) -> httpx.Response:
    """Замена агрегата (`replaceAggregateStatus`) — ответ как есть, для проверок ошибок."""
    return client.post(
        f"{API}/vehicles/{vid}/aggregate-statuses/{code}/replace", json=body, headers=headers
    )


def replace(client: TestClient, headers: Headers, vid: int, code: str, day: date, km: int) -> None:
    """Замена агрегата, которая должна пройти."""
    r = post_replace(client, headers, vid, code, replaced_at=str(day), mileage_at_replacement=km)
    assert r.status_code == 200, r.text


def set_mileage(client: TestClient, headers: Headers, vid: int, km: int) -> None:
    r = client.patch(f"{API}/vehicles/{vid}/mileage", json={"mileage": km}, headers=headers)
    assert r.status_code == 200, r.text
