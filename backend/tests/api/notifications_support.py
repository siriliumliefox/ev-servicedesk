"""Общее для тестов Notifications (Глава 15, ADR 0019): лента и публикация.

Фикстуры клиентов с авто и токенами, фейкового отправителя и worker — tests/api/conftest.py.
"""

from fastapi.testclient import TestClient

from tests.api.conftest import API, Headers


def feed(client: TestClient, headers: Headers, **params) -> dict:
    r = client.get(f"{API}/notifications", params=params, headers=headers)
    assert r.status_code == 200, r.text
    return r.json()


def publish(client: TestClient, admin: Headers, **body) -> dict:
    r = client.post(f"{API}/notifications", json=body, headers=admin)
    assert r.status_code == 201, r.text
    return r.json()


def regulation(client: TestClient, admin: Headers, model: int, code: str, **interval) -> None:
    r = client.post(
        f"{API}/maintenance-regulations",
        json={"vehicle_model_id": model, "aggregate_type_code": code, **interval},
        headers=admin,
    )
    assert r.status_code == 201, r.text
