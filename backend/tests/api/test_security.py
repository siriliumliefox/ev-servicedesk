"""Безопасность: запросы без токена / с негодным / с чужим токеном → 401/403 (Глава 10)."""

import re
from datetime import UTC, datetime, timedelta

import jwt
import pytest
from fastapi.routing import APIRoute
from sqlalchemy.orm import Session

from app.core.security import create_access_token
from app.main import create_app
from app.models import AppUser
from app.models.enums import UserRole
from tests.api.conftest import API, STAFF_PASSWORD, ContractClient, api_settings, bearer

# Тела, проходящие валидацию, — чтобы 401/403 не маскировались 422.
BODIES = {
    "logout": {"refresh_token": "x"},
    "linkTelegram": {"telegram_id": "tg-1"},
    "createVehicle": {"vin": "L6TZ0010000000001"},
    "updateVehicleMileage": {"mileage": 1},
    "correctVehicleMileage": {"expected_current_mileage": 1, "mileage": 0, "reason": "x"},
    "createMaintenanceRecord": {"performed_at": "2026-01-01", "mileage_at_service": 1},
    "createAggregateType": {"code": "brake_fluid", "name": "Тормозная жидкость"},
    "reviseMaintenanceRegulation": {
        "vehicle_model_id": 1,
        "aggregate_type_code": "engine_oil",
        "interval_km": 10000,
    },
    "replaceAggregateStatus": {"replaced_at": "2026-01-01", "mileage_at_replacement": 0},
    "updateAggregateStatusThresholds": {"yellow_from_percent": 70, "red_above_percent": 100},
    "createPresignedUpload": {"file_name": "photo.jpg", "file_type": "photo"},
    "createTicket": {"vehicle_id": 1, "category": "sim", "description": "x"},
    "updateTicketStatus": {"status": "resolved"},
    "assignTicket": {"assigned_engineer_id": None},
    "createTicketMessage": {"body": "x"},
    "createKnowledgeArticle": {"article_type": "guide", "title": "x", "content": ""},
    "updateKnowledgeArticle": {"title": "x"},
    "createDecisionTreeNode": {"question_text": "x", "is_root": True, "is_escalation": False},
    "updateDecisionTreeNode": {"question_text": "x", "is_root": True, "is_escalation": False},
    "createStaffUser": {"phone": "+375290000001", "role": "engineer", "password": "x" * 12},
    "updateUser": {"is_active": False},
    "resetUserPassword": {"password": "x" * 12},
}


def protected_routes(app) -> list[APIRoute]:
    return [
        r
        for r in app.routes
        if isinstance(r, APIRoute) and (r.openapi_extra or {}).get("x-required-roles")
    ]


def call(client, route: APIRoute, headers: dict | None = None):
    method = next(iter(route.methods)).lower()
    kwargs = {"headers": headers or {}}
    if route.operation_id in BODIES:
        kwargs["json"] = BODIES[route.operation_id]
    return client.request(method, re.sub(r"\{\w+\}", "1", route.path), **kwargs)


def test_protected_routes_exist(app):
    assert {r.operation_id for r in protected_routes(app)} == {
        "logout",
        "withdrawPdConsent",
        "linkTelegram",
        "getCurrentUser",
        # Vehicle Service (Глава 11)
        "searchVehicleModels",
        "listVehicles",
        "createVehicle",
        "getVehicle",
        "deleteVehicle",
        "updateVehicleMileage",
        "correctVehicleMileage",
        "listMaintenanceRecords",
        "createMaintenanceRecord",
        # Aggregates & Maintenance Service (Глава 12)
        "listAggregateTypes",
        "createAggregateType",
        "listMaintenanceRegulations",
        "reviseMaintenanceRegulation",
        "archiveMaintenanceRegulation",
        "listAggregateStatuses",
        "replaceAggregateStatus",
        "getAggregateStatusThresholds",
        "updateAggregateStatusThresholds",
        # Tickets Service и Uploads (Глава 13)
        "createPresignedUpload",
        "listTickets",
        "createTicket",
        "getTicket",
        "updateTicketStatus",
        "claimTicket",
        "assignTicket",
        "listTicketMessages",
        "createTicketMessage",
        # Knowledge Base Service (Глава 14)
        "listKnowledgeArticles",
        "createKnowledgeArticle",
        "getKnowledgeArticle",
        "updateKnowledgeArticle",
        "unpublishKnowledgeArticle",
        "listKnowledgeArticleRevisions",
        "getKnowledgeArticleRevision",
        "listDecisionTreeNodes",
        "createDecisionTreeNode",
        "validateDecisionTree",
        "updateDecisionTreeNode",
        "deleteDecisionTreeNode",
        # Notifications Service (Глава 15)
        "registerPushToken",
        "deletePushToken",
        "listNotifications",
        "createNotification",
        "listPublishedNotifications",
        "previewNotificationAudience",
        "markNotificationRead",
        "markNotificationOpened",
        "listFirmwareReleases",
        "createFirmwareRelease",
        "setVehicleFirmware",
        # Analytics Service (Глава 16)
        "getTicketResolutionStats",
        "listProblemModels",
        "getMaintenanceConversionStats",
        # Users (Глава 17)
        "listUsers",
        "createStaffUser",
        "getUser",
        "updateUser",
        # Сброс пароля сотрудника (Глава 22)
        "resetUserPassword",
    }


@pytest.mark.parametrize(
    "headers",
    [
        {},
        {"Authorization": "Bearer"},
        {"Authorization": "Bearer not-a-jwt"},
        {"Authorization": "Basic dXNlcjpwYXNz"},
        {"Authorization": "Token abc"},
    ],
    ids=["none", "empty-bearer", "garbage", "basic", "other-scheme"],
)
def test_no_or_malformed_token_401(app, client, headers):
    for route in protected_routes(app):
        r = call(client, route, headers)
        assert r.status_code == 401, (route.path, r.text)
        assert r.json()["error"]["code"] == "UNAUTHORIZED"
        assert r.headers["WWW-Authenticate"] == "Bearer"


def test_expired_token_401(app, client, make_client_user, settings):
    user = make_client_user("+375291000001")
    past = datetime.now(UTC) - timedelta(hours=1)
    token = create_access_token(user.id, "client", settings, now=past)
    for route in protected_routes(app):
        assert call(client, route, bearer(token)).status_code == 401


def test_token_with_foreign_secret_401(app, client, make_client_user):
    user = make_client_user("+375291000002")
    foreign = api_settings(jwt_secret="attacker-secret-" + "a" * 32)
    token = create_access_token(user.id, "admin", foreign)
    for route in protected_routes(app):
        assert call(client, route, bearer(token)).status_code == 401


def test_forged_role_claim_ignored(client, make_client_user, settings):
    """Роль берётся из БД: даже валидно подписанный токен с role=admin не даёт прав админа."""
    user = make_client_user("+375291000003")
    now = datetime.now(UTC)
    token = jwt.encode(
        {
            "sub": str(user.id),
            "role": "admin",
            "typ": "access",
            "iss": settings.jwt_issuer,
            "aud": settings.jwt_audience,
            "iat": int(now.timestamp()),
            "exp": int((now + timedelta(minutes=5)).timestamp()),
        },
        settings.jwt_secret,
        algorithm="HS256",
    )
    me = client.get(f"{API}/me", headers=bearer(token))
    assert me.status_code == 200 and me.json()["role"] == "client"


def test_refresh_token_is_not_access_token(client, login_client):
    session = login_client("+375291000004")
    r = client.get(f"{API}/me", headers=bearer(session["refresh_token"]))
    assert r.status_code == 401


def test_token_of_deleted_or_disabled_user_401(client, login_client, db: Session):
    session = login_client("+375291000005")
    user = db.get(AppUser, session["user"]["id"])
    user.is_active = False
    db.commit()
    r = client.get(f"{API}/me", headers=bearer(session["access_token"]))
    assert r.status_code == 401
    # Неизвестный пользователь
    ghost = create_access_token(10**9, "client", api_settings())
    assert client.get(f"{API}/me", headers=bearer(ghost)).status_code == 401


@pytest.mark.parametrize("role", [UserRole.ENGINEER, UserRole.ADMIN])
def test_staff_forbidden_on_client_only_routes(client, make_staff, role):
    phone = "+37529555000" + ("1" if role is UserRole.ENGINEER else "2")
    make_staff(phone, role)
    token = client.post(
        f"{API}/auth/staff/login", json={"phone": phone, "password": STAFF_PASSWORD}
    ).json()["access_token"]
    r = client.delete(f"{API}/auth/pd-consent", headers=bearer(token))
    assert r.status_code == 403 and r.json()["error"]["code"] == "FORBIDDEN"
    r = client.post(
        f"{API}/auth/telegram/link", json={"telegram_id": "tg-x"}, headers=bearer(token)
    )
    assert r.status_code == 403
    # Доступное всем ролям — доступно.
    assert client.get(f"{API}/me", headers=bearer(token)).status_code == 200


def test_logout_cannot_revoke_foreign_refresh(client, login_client):
    """Object-level: чужой refresh-токен через logout не отзывается."""
    victim = login_client("+375291000006")
    attacker = login_client("+375291000007")
    r = client.post(
        f"{API}/auth/logout",
        json={"refresh_token": victim["refresh_token"]},
        headers=bearer(attacker["access_token"]),
    )
    assert r.status_code == 204
    r = client.post(f"{API}/auth/refresh", json={"refresh_token": victim["refresh_token"]})
    assert r.status_code == 200


STRONG = "s" * 40


@pytest.mark.parametrize(
    "overrides",
    [
        {"environment": "test"},
        # S3-ключи обязательны вне local/test (ADR 0017 п. 11); бакет create_app не проверяет —
        # проверка в lifespan при старте.
        {
            "environment": "staging",
            "jwt_secret": STRONG,
            "sms_code_secret": STRONG,
            "s3_access_key": "k" * 20,
            "s3_secret_key": STRONG,
        },
        {
            "environment": "production",
            "jwt_secret": STRONG,
            "sms_code_secret": STRONG,
            "s3_access_key": "k" * 20,
            "s3_secret_key": STRONG,
            "sms_provider": "a1",
            "sms_provider_user": "375290000000",
            "sms_provider_api_key": "k",
            "push_provider": "fcm",
            "fcm_service_account_json": "{}",
        },
        # local, но с реальным провайдером: кода в памяти нет — маршрута тоже.
        {
            "environment": "local",
            "sms_provider": "a1",
            "sms_provider_user": "1",
            "sms_provider_api_key": "k",
        },
    ],
    ids=["test", "staging", "production", "local-a1"],
)
def test_debug_route_not_mounted_outside_local_fake(overrides):
    """Проверка по таблице маршрутов: 404 по HTTP ничего не доказывает (как и у пустого пути)."""
    application = create_app(api_settings(**overrides))
    assert not any("_debug" in getattr(r, "path", "") for r in application.routes)


def test_errors_do_not_leak_internals(client):
    r = client.post(
        f"{API}/auth/refresh", content=b"{not json", headers={"Content-Type": "application/json"}
    )
    assert r.status_code == 422
    assert "Traceback" not in r.text


def test_debug_route_local_only_returns_code(db, real_redis):
    """ENVIRONMENT=local: код фейкового SMS доступен только через /_debug, вне OpenAPI."""

    from app.api.deps import get_sms_provider
    from app.core.config import get_settings
    from app.core.db import get_db
    from app.core.redis import get_redis
    from app.domain.auth.sms import fake_provider

    settings = api_settings(environment="local")
    local = create_app(settings)
    assert any("_debug" in getattr(r, "path", "") for r in local.routes)
    local.dependency_overrides[get_settings] = lambda: settings
    local.dependency_overrides[get_db] = lambda: db
    local.dependency_overrides[get_redis] = lambda: real_redis
    # Явно модульный фейк: /_debug читает именно его; реальный провайдер исключён.
    local.dependency_overrides[get_sms_provider] = fake_provider
    c = ContractClient(local)
    phone = "+375291000099"
    assert c.post(f"{API}/auth/phone/request-code", json={"phone": phone}).status_code == 200
    r = c.get(f"{API}/_debug/sms/last-code", params={"phone": phone})
    assert r.status_code == 200
    code = r.json()["code"]
    r = c.post(
        f"{API}/auth/phone/verify-code",
        json={"phone": phone, "code": code, "pd_policy_version": "2026-10"},
    )
    assert r.status_code == 200
    assert not any("_debug" in p for p in local.openapi()["paths"])
