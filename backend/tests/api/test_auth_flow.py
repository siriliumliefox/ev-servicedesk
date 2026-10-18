"""Интеграция: регистрация → подтверждение → доступ к ресурсу и остальные сценарии Auth.

Реальные PostgreSQL и Redis; каждый ответ сверяется с docs/openapi.yaml (assert_contract).
"""

from datetime import UTC, datetime

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import get_sms_provider
from app.core.security import create_access_token
from app.domain.auth.codes import code_key
from app.domain.auth.sms import SmsError
from app.models import AppUser, PdConsent, RefreshToken
from app.models.enums import UserRole
from tests.api.conftest import (
    API,
    POLICY,
    STAFF_PASSWORD,
    bearer,
    code_from,
)

PHONE = "+375291112233"
OTHER = "+375291112244"


def test_register_verify_access_refresh_logout(client, sms, db: Session):
    # 1. Запрос кода
    r = client.post(f"{API}/auth/phone/request-code", json={"phone": PHONE})
    assert r.status_code == 200 and r.json()["ttl_seconds"] == 120

    # 2. Подтверждение — регистрация клиента с согласием на ПД
    r = client.post(
        f"{API}/auth/phone/verify-code",
        json={"phone": PHONE, "code": code_from(sms, PHONE), "pd_policy_version": POLICY},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["is_new_user"] is True
    assert body["user"]["role"] == "client" and body["user"]["phone"] == PHONE
    assert body["expires_in"] == 900

    user = db.scalars(select(AppUser).where(AppUser.phone == PHONE)).one()
    consent = db.scalars(select(PdConsent).where(PdConsent.user_id == user.id)).one()
    assert consent.policy_version == POLICY and consent.withdrawn_at is None
    stored = db.scalars(select(RefreshToken).where(RefreshToken.user_id == user.id)).one()
    assert stored.token_hash != body["refresh_token"]  # в БД только хэш

    # 3. Доступ к ресурсу
    r = client.get(f"{API}/me", headers=bearer(body["access_token"]))
    assert r.status_code == 200 and r.json()["id"] == user.id

    # 4. Ротация refresh
    r = client.post(f"{API}/auth/refresh", json={"refresh_token": body["refresh_token"]})
    assert r.status_code == 200
    rotated = r.json()
    assert rotated["refresh_token"] != body["refresh_token"]

    # 5. Выход: refresh отозван
    r = client.post(
        f"{API}/auth/logout",
        json={"refresh_token": rotated["refresh_token"]},
        headers=bearer(rotated["access_token"]),
    )
    assert r.status_code == 204
    r = client.post(f"{API}/auth/refresh", json={"refresh_token": rotated["refresh_token"]})
    assert r.status_code == 401


def test_code_is_single_use(client, sms):
    client.post(f"{API}/auth/phone/request-code", json={"phone": PHONE})
    code = code_from(sms, PHONE)
    payload = {"phone": PHONE, "code": code, "pd_policy_version": POLICY}
    assert client.post(f"{API}/auth/phone/verify-code", json=payload).status_code == 200
    r = client.post(f"{API}/auth/phone/verify-code", json=payload)
    assert r.status_code == 400 and r.json()["error"]["code"] == "CODE_EXPIRED"


def test_wrong_code_then_correct(client, sms):
    client.post(f"{API}/auth/phone/request-code", json={"phone": PHONE})
    code = code_from(sms, PHONE)
    wrong = "0000" if code != "0000" else "1111"
    r = client.post(
        f"{API}/auth/phone/verify-code",
        json={"phone": PHONE, "code": wrong, "pd_policy_version": POLICY},
    )
    assert r.status_code == 400
    assert r.json()["error"] == {
        "code": "CODE_INVALID",
        "message": "Неверный код",
        "details": {"attempts_left": 4},
    }
    r = client.post(
        f"{API}/auth/phone/verify-code",
        json={"phone": PHONE, "code": code, "pd_policy_version": POLICY},
    )
    assert r.status_code == 200


def test_attempts_exhausted_429(client, sms):
    client.post(f"{API}/auth/phone/request-code", json={"phone": PHONE})
    code = code_from(sms, PHONE)
    wrong = "0000" if code != "0000" else "1111"
    payload = {"phone": PHONE, "code": wrong, "pd_policy_version": POLICY}
    responses = [client.post(f"{API}/auth/phone/verify-code", json=payload) for _ in range(5)]
    assert [r.status_code for r in responses] == [400, 400, 400, 400, 429]
    assert int(responses[-1].headers["Retry-After"]) > 0
    r = client.post(f"{API}/auth/phone/verify-code", json=payload)  # код уже сгорел
    r = client.post(
        f"{API}/auth/phone/verify-code",
        json={"phone": PHONE, "code": code, "pd_policy_version": POLICY},
    )
    assert r.status_code == 400 and r.json()["error"]["code"] == "CODE_EXPIRED"


def test_resend_rate_limited_429(client):
    assert client.post(f"{API}/auth/phone/request-code", json={"phone": PHONE}).status_code == 200
    r = client.post(f"{API}/auth/phone/request-code", json={"phone": PHONE})
    assert r.status_code == 429
    assert int(r.headers["Retry-After"]) > 0


def test_consent_required_does_not_burn_code(client, sms, db: Session):
    client.post(f"{API}/auth/phone/request-code", json={"phone": PHONE})
    code = code_from(sms, PHONE)
    r = client.post(f"{API}/auth/phone/verify-code", json={"phone": PHONE, "code": code})
    assert r.status_code == 422 and r.json()["error"]["code"] == "PD_CONSENT_REQUIRED"
    assert db.scalar(select(func.count()).select_from(AppUser).where(AppUser.phone == PHONE)) == 0
    r = client.post(
        f"{API}/auth/phone/verify-code",
        json={"phone": PHONE, "code": code, "pd_policy_version": POLICY},
    )
    assert r.status_code == 200


def test_existing_client_login_without_new_consent(client, sms, make_client_user):
    user = make_client_user(PHONE)
    client.post(f"{API}/auth/phone/request-code", json={"phone": PHONE})
    r = client.post(
        f"{API}/auth/phone/verify-code", json={"phone": PHONE, "code": code_from(sms, PHONE)}
    )
    assert r.status_code == 200
    assert r.json()["is_new_user"] is False and r.json()["user"]["id"] == user.id


def test_new_policy_version_replaces_consent(client, sms, db: Session, make_client_user):
    user = make_client_user(PHONE)
    client.post(f"{API}/auth/phone/request-code", json={"phone": PHONE})
    r = client.post(
        f"{API}/auth/phone/verify-code",
        json={"phone": PHONE, "code": code_from(sms, PHONE), "pd_policy_version": "2027-01"},
    )
    assert r.status_code == 200
    rows = db.scalars(select(PdConsent).where(PdConsent.user_id == user.id)).all()
    active = [c for c in rows if c.withdrawn_at is None]
    assert len(rows) == 2 and [c.policy_version for c in active] == ["2027-01"]


@pytest.mark.parametrize("kind", ["blocked-client", "staff", "blocked-staff"])
def test_no_sms_for_blocked_client_or_staff(
    client, sms, real_redis, make_client_user, make_staff, kind
):
    """#103 (ADR 0029 п. 15): ответ как обычно, но код не создаётся и платное SMS не уходит."""
    if kind == "blocked-client":
        make_client_user(PHONE, active=False)
    else:
        make_staff(PHONE, active=kind == "staff")
    r = client.post(f"{API}/auth/phone/request-code", json={"phone": PHONE})
    assert r.status_code == 200 and r.json() == {"ttl_seconds": 120}
    assert sms.sent_count == 0 and not real_redis.exists(code_key(PHONE))
    # Тот же ответ, что и у свободного номера: состояние номера не раскрывается.
    assert client.post(f"{API}/auth/phone/request-code", json={"phone": OTHER}).json() == r.json()
    r = client.post(f"{API}/auth/phone/verify-code", json={"phone": PHONE, "code": "0000"})
    assert r.status_code == 400 and r.json()["error"]["code"] == "CODE_EXPIRED"


def test_disabled_client_cannot_login(client, sms, make_client_user, db: Session):
    """Вторая линия: заблокирован после выпуска кода — вход по коду отклоняется."""
    user = make_client_user(PHONE)
    client.post(f"{API}/auth/phone/request-code", json={"phone": PHONE})
    user.is_active = False
    db.commit()
    r = client.post(
        f"{API}/auth/phone/verify-code", json={"phone": PHONE, "code": code_from(sms, PHONE)}
    )
    assert r.status_code == 400 and r.json()["error"]["code"] == "ACCOUNT_DISABLED"


def test_staff_cannot_use_sms_login(client, sms, make_staff):
    """Вторая линия: номер стал служебным после выпуска кода — входа по SMS нет."""
    client.post(f"{API}/auth/phone/request-code", json={"phone": PHONE})
    make_staff(PHONE)
    r = client.post(
        f"{API}/auth/phone/verify-code",
        json={"phone": PHONE, "code": code_from(sms, PHONE), "pd_policy_version": POLICY},
    )
    assert r.status_code == 400 and r.json()["error"]["code"] == "STAFF_PASSWORD_LOGIN"


def test_invalid_phone_422(client):
    r = client.post(f"{API}/auth/phone/request-code", json={"phone": "80291234567"})
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "VALIDATION_ERROR"
    assert "80291234567" not in r.text  # введённое значение не возвращается


def test_staff_login_and_access(client, make_staff):
    staff = make_staff("+375295550001", UserRole.ADMIN)
    r = client.post(
        f"{API}/auth/staff/login", json={"phone": "+375295550001", "password": STAFF_PASSWORD}
    )
    assert r.status_code == 200 and r.json()["user"]["role"] == "admin"
    me = client.get(f"{API}/me", headers=bearer(r.json()["access_token"]))
    assert me.status_code == 200 and me.json()["id"] == staff.id


def test_staff_login_failures(client, make_staff):
    make_staff("+375295550002")
    make_staff("+375295550003", active=False)
    cases = [
        {"phone": "+375295550002", "password": "wrong"},
        {"phone": "+375295550009", "password": STAFF_PASSWORD},  # нет такого
        {"phone": "+375295550003", "password": STAFF_PASSWORD},  # заблокирован
    ]
    for payload in cases:
        r = client.post(f"{API}/auth/staff/login", json=payload)
        assert r.status_code == 401
        assert r.json()["error"]["message"] == "Неверный телефон или пароль"


def test_client_cannot_use_staff_login(client, make_client_user):
    make_client_user(PHONE)
    r = client.post(f"{API}/auth/staff/login", json={"phone": PHONE, "password": "x"})
    assert r.status_code == 401


def test_staff_login_rate_limited(client, make_staff):
    make_staff("+375295550004")
    payload = {"phone": "+375295550004", "password": "wrong"}
    statuses = [client.post(f"{API}/auth/staff/login", json=payload).status_code for _ in range(6)]
    assert statuses == [401] * 5 + [429]
    # Даже верный пароль заблокирован до конца окна.
    r = client.post(
        f"{API}/auth/staff/login", json={"phone": "+375295550004", "password": STAFF_PASSWORD}
    )
    assert r.status_code == 429
    assert int(r.headers["Retry-After"]) > 0


def test_refresh_reuse_revokes_all_sessions(client, login_client, db: Session):
    first = login_client(PHONE)
    rotated = client.post(f"{API}/auth/refresh", json={"refresh_token": first["refresh_token"]})
    assert rotated.status_code == 200
    # Повторное предъявление старого токена — кража: отзываются все токены пользователя.
    r = client.post(f"{API}/auth/refresh", json={"refresh_token": first["refresh_token"]})
    assert r.status_code == 401
    r = client.post(f"{API}/auth/refresh", json={"refresh_token": rotated.json()["refresh_token"]})
    assert r.status_code == 401
    user_id = first["user"]["id"]
    active = db.scalar(
        select(func.count())
        .select_from(RefreshToken)
        .where(RefreshToken.user_id == user_id, RefreshToken.revoked_at.is_(None))
    )
    assert active == 0


def test_unknown_refresh_token_401(client):
    r = client.post(f"{API}/auth/refresh", json={"refresh_token": "nope"})
    assert r.status_code == 401


def test_withdraw_pd_consent(client, login_client, db: Session, settings):
    session = login_client(PHONE)
    headers = bearer(session["access_token"])
    r = client.delete(f"{API}/auth/pd-consent", headers=headers)
    assert r.status_code == 202
    consent = db.scalars(select(PdConsent).where(PdConsent.user_id == session["user"]["id"])).one()
    assert consent.withdrawn_at is not None
    # Все refresh-токены отозваны.
    r = client.post(f"{API}/auth/refresh", json={"refresh_token": session["refresh_token"]})
    assert r.status_code == 401
    # И выданный access-токен (ADR 0029 п. 12).
    assert client.delete(f"{API}/auth/pd-consent", headers=headers).status_code == 401
    later = bearer(create_access_token(session["user"]["id"], "client", settings))
    r = client.delete(f"{API}/auth/pd-consent", headers=later)
    assert r.status_code == 409 and r.json()["error"]["code"] == "PD_CONSENT_NOT_ACTIVE"


def test_telegram_link(client, login_client):
    a = login_client(PHONE)
    b = login_client("+375291112244")
    r = client.post(
        f"{API}/auth/telegram/link",
        json={"telegram_id": "tg-100"},
        headers=bearer(a["access_token"]),
    )
    assert r.status_code == 200 and r.json()["telegram_id"] == "tg-100"
    r = client.post(
        f"{API}/auth/telegram/link",
        json={"telegram_id": "tg-100"},
        headers=bearer(b["access_token"]),
    )
    assert r.status_code == 409 and r.json()["error"]["code"] == "TELEGRAM_ALREADY_LINKED"


class _FailingSms:
    def __init__(self, **flags: bool) -> None:
        self.flags = flags

    def send(self, phone: str, text: str) -> None:
        raise SmsError("down", **self.flags)


@pytest.mark.parametrize(
    ("flags", "status", "code"),
    [
        ({}, 503, "SMS_UNAVAILABLE"),
        ({"delivery_unknown": True}, 503, "SMS_UNAVAILABLE"),
        ({"invalid_recipient": True}, 422, "PHONE_NOT_SUPPORTED"),
    ],
    ids=["not-sent", "delivery-unknown", "invalid-recipient"],
)
def test_sms_provider_failure_contract(app, client, flags, status, code):
    app.dependency_overrides[get_sms_provider] = lambda: _FailingSms(**flags)
    r = client.post(f"{API}/auth/phone/request-code", json={"phone": PHONE})
    assert r.status_code == status and r.json()["error"]["code"] == code
    # Не отправлено — можно сразу повторить; доставка неизвестна — только после паузы.
    again = client.post(f"{API}/auth/phone/request-code", json={"phone": PHONE})
    assert again.status_code == (429 if flags.get("delivery_unknown") else status)


def test_blank_policy_version_is_consent_required_and_keeps_code(client, sms):
    client.post(f"{API}/auth/phone/request-code", json={"phone": PHONE})
    code = code_from(sms, PHONE)
    r = client.post(
        f"{API}/auth/phone/verify-code",
        json={"phone": PHONE, "code": code, "pd_policy_version": "   "},
    )
    assert r.status_code == 422 and r.json()["error"]["code"] == "PD_CONSENT_REQUIRED"
    r = client.post(
        f"{API}/auth/phone/verify-code",
        json={"phone": PHONE, "code": code, "pd_policy_version": f" {POLICY} "},
    )
    assert r.status_code == 200


def test_control_characters_rejected_422(client, login_client):
    session = login_client(PHONE)
    r = client.post(
        f"{API}/auth/telegram/link",
        json={"telegram_id": "tg\u0000x"},
        headers=bearer(session["access_token"]),
    )
    assert r.status_code == 422


def test_anonymized_user_with_phone_cannot_log_in(client, sms, make_client_user, make_staff, db):
    """Вход проверяет доступность (активен и не анонимизирован), как все запросы (ревью гл. 17)."""
    phone = "+375296900001"
    user = make_client_user(phone)
    user.anonymized_at = datetime.now(UTC)
    staff = make_staff("+375296900002")
    staff.anonymized_at = datetime.now(UTC)
    db.commit()
    client.post(f"{API}/auth/phone/request-code", json={"phone": phone})
    r = client.post(
        f"{API}/auth/phone/verify-code", json={"phone": phone, "code": code_from(sms, phone)}
    )
    assert r.status_code == 400 and r.json()["error"]["code"] == "ACCOUNT_DISABLED"
    r = client.post(
        f"{API}/auth/staff/login", json={"phone": "+375296900002", "password": STAFF_PASSWORD}
    )
    assert r.status_code == 401
