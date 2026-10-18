"""Сессии и вход сотрудников (Глава 25, #102, ADR 0029 пп. 11–13).

- выход, сброс пароля, блокировка, отзыв согласия и повторное предъявление refresh отзывают
  выданные access-токены сразу, а не через 15 минут;
- блокировка входа — по паре «номер + IP»: злоумышленник со своего адреса не запирает
  сотрудника; общий потолок на номер — против подбора с многих адресов;
- сброс пароля снимает блокировку входа номера;
- пароль сотрудника проверяется на стойкость (zxcvbn ≥ 3, номер — известные данные).
"""

import logging
import secrets

import pytest
from redis import Redis
from sqlalchemy.orm import Session

from app.core.errors import ApiError
from app.domain.auth import revocation, service
from app.models.enums import UserRole
from tests.api.conftest import API, STAFF_PASSWORD, api_settings, bearer

STAFF = "+375296680001"
ADMIN = "+375296680002"
NEW_PASSWORD = secrets.token_urlsafe(18)  # стойкий; в коде не хранится (gitleaks)


def staff_login(client, phone: str = STAFF, password: str = STAFF_PASSWORD):
    return client.post(f"{API}/auth/staff/login", json={"phone": phone, "password": password})


# ---------- Отзыв access-токенов ----------


def test_logout_revokes_presented_access_token_only(client, make_staff):
    make_staff(STAFF)
    first, second = staff_login(client).json(), staff_login(client).json()
    r = client.post(
        f"{API}/auth/logout",
        json={"refresh_token": first["refresh_token"]},
        headers=bearer(first["access_token"]),
    )
    assert r.status_code == 204
    me = client.get(f"{API}/me", headers=bearer(first["access_token"]))
    assert me.status_code == 401 and me.json()["error"]["code"] == "UNAUTHORIZED"
    # Другая сессия того же сотрудника продолжает работать.
    assert client.get(f"{API}/me", headers=bearer(second["access_token"])).status_code == 200


def test_password_reset_revokes_all_sessions_at_once(client, make_staff):
    make_staff(STAFF)
    make_staff(ADMIN, UserRole.ADMIN)
    session = staff_login(client).json()
    admin = bearer(staff_login(client, ADMIN).json()["access_token"])
    user_id = session["user"]["id"]
    r = client.post(
        f"{API}/users/{user_id}/password", json={"password": NEW_PASSWORD}, headers=admin
    )
    assert r.status_code == 204
    assert client.get(f"{API}/me", headers=bearer(session["access_token"])).status_code == 401
    r = client.post(f"{API}/auth/refresh", json={"refresh_token": session["refresh_token"]})
    assert r.status_code == 401
    assert staff_login(client, password=NEW_PASSWORD).status_code == 200


def test_refresh_reuse_revokes_access_tokens(client, login_client):
    first = login_client("+375296680003")
    rotated = client.post(f"{API}/auth/refresh", json={"refresh_token": first["refresh_token"]})
    assert rotated.status_code == 200
    reused = client.post(f"{API}/auth/refresh", json={"refresh_token": first["refresh_token"]})
    assert reused.status_code == 401
    # Вор успел получить новую пару — её access тоже больше не действует.
    new_access = rotated.json()["access_token"]
    assert client.get(f"{API}/me", headers=bearer(new_access)).status_code == 401


def test_redis_down_fails_closed(client, make_staff, monkeypatch):
    make_staff(STAFF)
    token = staff_login(client).json()["access_token"]

    def broken(*_args, **_kwargs):
        from redis.exceptions import ConnectionError as RedisConnectionError

        raise RedisConnectionError("down")

    monkeypatch.setattr(Redis, "mget", broken)
    with client.unchecked():
        r = client.get(f"{API}/me", headers=bearer(token))
    assert r.status_code == 503 and r.json()["error"]["code"] == "SERVICE_UNAVAILABLE"


# ---------- Блокировка входа (B1 №3) ----------


def login_from(db, redis, settings, ip: str, password: str = "wrong-password"):
    try:
        return service.staff_login(db, redis, settings, STAFF, password, ip)
    except ApiError as exc:
        return exc.status_code


def test_lockout_is_per_phone_and_ip(db: Session, real_redis, settings, make_staff):
    make_staff(STAFF)
    attacker = [login_from(db, real_redis, settings, "203.0.113.7") for _ in range(6)]
    assert attacker == [401] * 5 + [429]
    assert login_from(db, real_redis, settings, "203.0.113.7", STAFF_PASSWORD) == 429
    # Сотрудник со своего адреса входит: чужие неудачи его не запирают.
    ok = login_from(db, real_redis, settings, "198.51.100.20", STAFF_PASSWORD)
    assert not isinstance(ok, int) and ok.user.phone == STAFF


def test_phone_ceiling_stops_distributed_guessing(db: Session, real_redis, make_staff, caplog):
    settings = api_settings(staff_login_failures_per_phone_hour=6)
    make_staff(STAFF)
    with caplog.at_level(logging.WARNING, logger="app.domain.auth.service"):
        results = [login_from(db, real_redis, settings, f"203.0.113.{i}") for i in range(10)]
    assert results == [401] * 6 + [429] * 4
    warnings = [r for r in caplog.records if "Подбор пароля" in r.getMessage()]
    assert len(warnings) == 1 and STAFF not in caplog.text, "один WARNING, номер в маске"


def test_password_reset_clears_lockout(client, db: Session, real_redis, settings, make_staff):
    staff = make_staff(STAFF)
    make_staff(ADMIN, UserRole.ADMIN)
    admin = bearer(staff_login(client, ADMIN).json()["access_token"])
    for _ in range(6):
        login_from(db, real_redis, settings, "203.0.113.9")
    assert login_from(db, real_redis, settings, "203.0.113.9", STAFF_PASSWORD) == 429
    r = client.post(
        f"{API}/users/{staff.id}/password", json={"password": NEW_PASSWORD}, headers=admin
    )
    assert r.status_code == 204
    ok = login_from(db, real_redis, settings, "203.0.113.9", NEW_PASSWORD)
    assert not isinstance(ok, int)


# ---------- Политика паролей (B1 №5) ----------

WEAK = [
    "aaaaaaaaaaaa",  # B1 №5
    "password1234",
    "qwertyuiop12",
    "375296680001ab",  # цифры своего номера
    "1234567890123",
]


@pytest.mark.parametrize("password", WEAK)
def test_weak_staff_password_rejected(client, make_staff, password):
    make_staff(ADMIN, UserRole.ADMIN)
    admin = bearer(staff_login(client, ADMIN).json()["access_token"])
    body = {"phone": STAFF, "role": "engineer", "password": password}
    r = client.post(f"{API}/users", json=body, headers=admin)
    assert r.status_code == 422, r.text
    error = r.json()["error"]
    assert (
        error["code"] == "VALIDATION_ERROR"
        and error["details"]["fields"][0]["loc"][-1] == "password"
    )
    assert password not in r.text, "введённый пароль не возвращается"


def test_weak_password_reset_rejected(client, make_staff):
    staff = make_staff(STAFF)
    make_staff(ADMIN, UserRole.ADMIN)
    admin = bearer(staff_login(client, ADMIN).json()["access_token"])
    r = client.post(f"{API}/users/{staff.id}/password", json={"password": "a" * 12}, headers=admin)
    assert r.status_code == 422
    assert staff_login(client).status_code == 200, "старый пароль и сессии не тронуты"


def test_strong_password_accepted(client, make_staff):
    make_staff(ADMIN, UserRole.ADMIN)
    admin = bearer(staff_login(client, ADMIN).json()["access_token"])
    body = {"phone": STAFF, "role": "engineer", "password": NEW_PASSWORD}
    assert client.post(f"{API}/users", json=body, headers=admin).status_code == 201
    assert staff_login(client, password=NEW_PASSWORD).status_code == 200


def test_revocation_marks_expire(real_redis, settings, make_staff, client):
    """Отметки отзыва не копятся: живут не дольше срока access-токена."""
    make_staff(STAFF)
    session = staff_login(client).json()
    user_id = session["user"]["id"]
    revocation.revoke_user_tokens(real_redis, settings, user_id)
    ttl = real_redis.ttl(revocation.SINCE_PREFIX + str(user_id))
    assert 0 < ttl <= settings.access_token_ttl_seconds + 60


# ---------- Смена пароля сотрудником (ADR 0029 п. 14) ----------


def change(client, headers, current: str, new: str):
    body = {"current_password": current, "new_password": new}
    return client.post(f"{API}/auth/staff/password", json=body, headers=headers)


def test_change_password_ends_other_sessions(client, make_staff):
    make_staff(STAFF)
    here, other = staff_login(client).json(), staff_login(client).json()
    r = change(client, bearer(here["access_token"]), STAFF_PASSWORD, NEW_PASSWORD)
    assert r.status_code == 200, r.text
    fresh = r.json()
    assert client.get(f"{API}/me", headers=bearer(fresh["access_token"])).status_code == 200
    for old in (here, other):
        assert client.get(f"{API}/me", headers=bearer(old["access_token"])).status_code == 401
        refresh = client.post(f"{API}/auth/refresh", json={"refresh_token": old["refresh_token"]})
        assert refresh.status_code == 401
    assert staff_login(client).status_code == 401
    assert staff_login(client, password=NEW_PASSWORD).status_code == 200


def test_wrong_current_password_counts_as_failed_login(client, make_staff):
    make_staff(STAFF)
    headers = bearer(staff_login(client).json()["access_token"])
    codes = [change(client, headers, "wrong-password", NEW_PASSWORD) for _ in range(6)]
    assert [r.status_code for r in codes] == [400] * 5 + [429]
    assert codes[0].json()["error"]["code"] == "PASSWORD_INVALID"
    assert staff_login(client).status_code == 429, "подбор через смену пароля не обходит лимит"


@pytest.mark.parametrize("new", ["aaaaaaaaaaaa", STAFF_PASSWORD, "375296680001xyz"])
def test_change_rejects_weak_or_same_password(client, make_staff, new):
    make_staff(STAFF)
    session = staff_login(client).json()
    r = change(client, bearer(session["access_token"]), STAFF_PASSWORD, new)
    assert r.status_code == 422, r.text
    assert r.json()["error"]["details"]["fields"][0]["loc"][-1] == "new_password"
    assert client.get(f"{API}/me", headers=bearer(session["access_token"])).status_code == 200
