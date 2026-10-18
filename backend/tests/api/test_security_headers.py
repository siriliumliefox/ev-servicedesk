"""Заголовки безопасности и Swagger (Глава 25, ADR 0029 п. 8, OWASP A02)."""

from fastapi.testclient import TestClient

from app.core.headers import HEADERS
from app.core.storage import get_storage
from app.main import create_app
from tests.api.conftest import API, api_settings


def test_security_headers_on_every_response(client, login_client):
    session = login_client("+375296720001")
    responses = [
        client.get(f"{API}/me", headers={"Authorization": f"Bearer {session['access_token']}"}),
        client.get(f"{API}/me"),  # 401
        client.get(f"{API}/no-such-route"),  # 404 вне контракта
        client.get("/health"),
    ]
    for r in responses:
        for name, value in HEADERS.items():
            assert r.headers.get(name) == value, (r.request.url, name)
    assert [r.headers.get("Cache-Control") for r in responses] == ["no-store"] * 3 + [None]


def test_swagger_hidden_in_production(fake_storage):
    settings = api_settings().model_copy(update={"environment": "production"})
    app = create_app(settings)
    app.dependency_overrides[get_storage] = lambda: fake_storage  # бакет при старте
    with TestClient(app) as client:
        for path in ("/docs", "/redoc", "/openapi.json"):
            assert client.get(path).status_code == 404, path


def test_swagger_available_outside_production():
    with TestClient(create_app(api_settings())) as client:
        assert client.get("/openapi.json").status_code == 200
