"""Метрики, JSON-журнал и события безопасности (глава 26, ADR 0030 пп. 13, 15).

- `/metrics` считает запросы по шаблону маршрута, как журнал доступа: значения параметров пути
  в метки не попадают; путь вне контракта и OpenAPI; пробы живости в журнал не пишутся.
- multiprocess (несколько процессов uvicorn): сумма из каталога, каталог очищается до старта.
- JSON-журнал: одна строка JSON, ПД замаскированы, лишние поля `extra` не выводятся.
- `app.security`: вход, выход, пароли, учётные записи, согласие, повтор refresh — с id и IP, без
  телефона.
"""

import json
import logging
import os
import subprocess
import sys
from pathlib import Path

import pytest

from app.core.logging import PiiStdoutHandler
from app.models.enums import UserRole
from tests.api.conftest import API, POLICY, STAFF_PASSWORD, bearer, code_from

STAFF_PHONE = "+375296810001"
CLIENT_PHONE = "+375296810002"
NEW_STAFF_PHONE = "+375296810003"
NEW_PASSWORD = "Ракета-Север-Гомель-2026"


def test_metrics_count_by_route_template(client) -> None:
    assert client.get(f"{API}/vehicles/987654").status_code == 401
    assert client.get(f"{API}/no-such-path-555").status_code == 404
    text = client.get("/metrics").text
    assert 'route="/v1/vehicles/{vehicleId}"' in text
    assert 'ev_http_request_duration_seconds_bucket{le="0.3",method="GET"' in text
    assert 'route="<unmatched>"' in text
    assert "987654" not in text and "no-such-path-555" not in text


def test_metrics_outside_contract(app) -> None:
    assert "/metrics" not in app.openapi()["paths"]


def test_probes_are_not_logged(client, caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO, logger="app.access")
    client.get("/health")
    client.get("/metrics")
    client.get(f"{API}/me")
    routes = [r.route for r in caplog.records if r.name == "app.access"]
    assert routes == ["/v1/me"]


def test_multiprocess_sums_and_resets(tmp_path: Path) -> None:
    """Режим multiprocess выбирается при импорте prometheus_client — отдельный процесс."""
    directory = tmp_path / "prom"
    directory.mkdir()
    (directory / "counter_999999.db").write_bytes(b"stale")
    (directory / "nested").mkdir()
    code = (
        "from app.core import metrics\n"
        "metrics.reset_multiproc_dir()\n"
        "metrics.observe_request('GET', '/v1/x', 200, 0.01)\n"
        "metrics.observe_request('GET', '/v1/x', 200, 0.02)\n"
        "print(metrics.render()[0].decode())\n"
    )
    env = {**os.environ, "PROMETHEUS_MULTIPROC_DIR": str(directory)}
    backend = Path(__file__).resolve().parents[2]
    out = subprocess.run(  # noqa: S603 — свой интерпретатор и свой код теста
        [sys.executable, "-c", code],
        env=env,
        cwd=backend,
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    assert 'ev_http_requests_total{method="GET",route="/v1/x",status="200"} 2.0' in out
    assert not (directory / "counter_999999.db").exists(), "файлы прошлого запуска удалены"
    assert not (directory / "nested").exists() and directory.is_dir(), "каталог (tmpfs) остаётся"


def test_json_format_masks_and_whitelists_fields() -> None:
    handler = PiiStdoutHandler("json")
    record = logging.LogRecord(
        "app.test", logging.WARNING, __file__, 1, "Звонок на %s", ("+375291234567",), None
    )
    record.event = "auth.staff_login"
    record.user_id = 7
    record.phone = "+375291234567"  # не из списка JSON_FIELDS — не выводится
    assert all(f.filter(record) for f in handler.filters)
    entry = json.loads(handler.format(record))
    assert entry["level"] == "WARNING" and entry["logger"] == "app.test"
    assert entry["event"] == "auth.staff_login" and entry["user_id"] == 7
    assert "1234567" not in entry["msg"] and "phone" not in entry
    assert entry["ts"].endswith("+00:00")


def security(caplog: pytest.LogCaptureFixture) -> list[logging.LogRecord]:
    return [r for r in caplog.records if r.name == "app.security"]


def test_security_events(client, sms, make_staff, db, caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO, logger="app.security")
    admin = make_staff(STAFF_PHONE, UserRole.ADMIN)

    wrong = client.post(
        f"{API}/auth/staff/login", json={"phone": STAFF_PHONE, "password": "x" * 12}
    )
    assert wrong.status_code == 401
    r = client.post(
        f"{API}/auth/staff/login", json={"phone": STAFF_PHONE, "password": STAFF_PASSWORD}
    )
    staff_headers = bearer(r.json()["access_token"])

    assert (
        client.post(f"{API}/auth/phone/request-code", json={"phone": CLIENT_PHONE}).status_code
        == 200
    )
    bad = client.post(f"{API}/auth/phone/verify-code", json={"phone": CLIENT_PHONE, "code": "0000"})
    assert bad.status_code == 400
    body = {
        "phone": CLIENT_PHONE,
        "code": code_from(sms, CLIENT_PHONE),
        "pd_policy_version": POLICY,
    }
    session = client.post(f"{API}/auth/phone/verify-code", json=body).json()
    client_headers = bearer(session["access_token"])
    refresh = session["refresh_token"]
    rotated = client.post(f"{API}/auth/refresh", json={"refresh_token": refresh})
    assert rotated.status_code == 200
    reuse = client.post(f"{API}/auth/refresh", json={"refresh_token": refresh})
    assert reuse.status_code == 401

    created = client.post(
        f"{API}/users",
        json={"phone": NEW_STAFF_PHONE, "role": "engineer", "password": NEW_PASSWORD},
        headers=staff_headers,
    ).json()
    client.patch(f"{API}/users/{created['id']}", json={"role": "admin"}, headers=staff_headers)
    client.patch(f"{API}/users/{created['id']}", json={"is_active": False}, headers=staff_headers)
    reset = client.post(
        f"{API}/users/{created['id']}/password",
        json={"password": NEW_PASSWORD + "!"},
        headers=staff_headers,
    )
    assert reset.status_code == 204

    second = client.post(f"{API}/auth/phone/request-code", json={"phone": CLIENT_PHONE})
    assert second.status_code in (200, 429)
    assert client.delete(f"{API}/auth/pd-consent", headers=client_headers).status_code in (202, 401)

    records = security(caplog)
    seen = {(r.event, r.outcome) for r in records}
    assert {
        ("auth.staff_login", "failure"),
        ("auth.staff_login", "success"),
        ("auth.client_login", "failure"),
        ("auth.client_registered", "success"),
        ("auth.refresh_reuse", "denied"),
        ("user.created", "success"),
        ("user.role_changed", "success"),
        ("user.blocked", "success"),
        ("user.password_reset", "success"),
    } <= seen
    login = next(r for r in records if r.event == "auth.staff_login" and r.outcome == "success")
    assert (login.user_id, login.role, login.ip) == (admin.id, "admin", "testclient")
    failure = next(r for r in records if r.event == "auth.staff_login" and r.outcome == "failure")
    assert failure.levelno == logging.WARNING and failure.target == "UNAUTHORIZED"
    blocked = next(r for r in records if r.event == "user.blocked")
    assert (blocked.user_id, blocked.target_user_id) == (admin.id, created["id"])
    for record in records:
        text = record.getMessage()
        assert "375296810" not in text, "телефона в событиях безопасности нет"


def test_refresh_after_blocking_is_not_reuse(client, login_client, as_staff, caplog) -> None:
    """#105 (№16): refresh-токен, отозванный блокировкой, — 401 без события повтора и без
    второго отзыва сессий; разблокированному — «Сессия завершена»."""
    caplog.set_level(logging.INFO, logger="app.security")
    admin_headers, _ = as_staff("+375296810071", UserRole.ADMIN)
    session = login_client("+375296810072")
    me = client.get(f"{API}/me", headers=bearer(session["access_token"])).json()
    blocked = client.patch(
        f"{API}/users/{me['id']}", json={"is_active": False}, headers=admin_headers
    )
    assert blocked.status_code == 200
    r = client.post(f"{API}/auth/refresh", json={"refresh_token": session["refresh_token"]})
    assert (r.status_code, r.json()["error"]["message"]) == (401, "Учётная запись недоступна")
    unblocked = client.patch(
        f"{API}/users/{me['id']}", json={"is_active": True}, headers=admin_headers
    )
    assert unblocked.status_code == 200
    r = client.post(f"{API}/auth/refresh", json={"refresh_token": session["refresh_token"]})
    assert (r.status_code, r.json()["error"]["message"]) == (
        401,
        "Сессия завершена — войдите заново",
    )
    assert "auth.refresh_reuse" not in {r.event for r in security(caplog)}


def test_logout_and_consent_withdrawal_events(client, login_client, caplog) -> None:
    caplog.set_level(logging.INFO, logger="app.security")
    session = login_client(CLIENT_PHONE)
    headers = bearer(session["access_token"])
    assert client.delete(f"{API}/auth/pd-consent", headers=headers).status_code == 202
    second = login_client("+375296810004")
    r = client.post(
        f"{API}/auth/logout",
        json={"refresh_token": second["refresh_token"]},
        headers=bearer(second["access_token"]),
    )
    assert r.status_code == 204
    events = {(r.event, r.user_id) for r in security(caplog)}
    assert ("pd.consent_withdrawn", session["user"]["id"]) in events
    assert ("auth.logout", second["user"]["id"]) in events


def test_password_change_events(client, as_staff, caplog) -> None:
    caplog.set_level(logging.INFO, logger="app.security")
    headers, user = as_staff("+375296810005")
    url = f"{API}/auth/staff/password"
    bad = client.post(
        url, json={"current_password": "x" * 12, "new_password": NEW_PASSWORD}, headers=headers
    )
    assert bad.status_code == 400
    ok = client.post(
        url,
        json={"current_password": STAFF_PASSWORD, "new_password": NEW_PASSWORD},
        headers=headers,
    )
    assert ok.status_code == 200
    events = [
        (r.event, r.outcome, r.user_id)
        for r in security(caplog)
        if r.event.startswith("auth.password")
    ]
    assert events == [
        ("auth.password_changed", "failure", user.id),
        ("auth.password_changed", "success", user.id),
    ]
