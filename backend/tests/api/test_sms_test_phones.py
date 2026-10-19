"""Тестовые номера SMS вне production (Глава 17, ADR 0021 п. 6).

Для номера из SMS_TEST_PHONES код — SMS_TEST_CODE, SMS не отправляется; проверка кода,
попытки и лимиты — как у обычных номеров. Так сквозной сценарий проходит регистрацию на
стеке с ENVIRONMENT=staging, где код из памяти процесса снаружи не получить.
"""

import pytest

from app.core.config import Settings
from tests.api.conftest import API, POLICY, api_settings, error_code

TEST_PHONE = "+375290000101"
REAL_PHONE = "+375290000102"
TEST_CODE = "7319"


@pytest.fixture
def settings() -> Settings:
    return api_settings(sms_test_phones=TEST_PHONE, sms_test_code=TEST_CODE)


def verify(client, phone: str, code: str):
    body = {"phone": phone, "code": code, "pd_policy_version": POLICY}
    return client.post(f"{API}/auth/phone/verify-code", json=body)


def test_test_phone_logs_in_with_secret_code_without_sms(client, sms):
    r = client.post(f"{API}/auth/phone/request-code", json={"phone": TEST_PHONE})
    assert r.status_code == 200
    assert sms.sent_count == 0, "на тестовый номер SMS не отправляется"
    r = verify(client, TEST_PHONE, TEST_CODE)
    assert r.status_code == 200 and r.json()["is_new_user"] is True


def test_test_phone_code_is_checked_and_limited(client, sms, settings):
    client.post(f"{API}/auth/phone/request-code", json={"phone": TEST_PHONE})
    r = verify(client, TEST_PHONE, "0000")
    assert r.status_code == 400 and error_code(r) == "CODE_INVALID"
    # Повторный запрос раньше паузы — 429, как у обычного номера.
    r = client.post(f"{API}/auth/phone/request-code", json={"phone": TEST_PHONE})
    assert r.status_code == 429
    # Код одноразовый: после входа повтор того же кода не принимается.
    assert verify(client, TEST_PHONE, TEST_CODE).status_code == 200
    assert error_code(verify(client, TEST_PHONE, TEST_CODE)) == "CODE_EXPIRED"


def test_test_code_without_request_is_rejected(client):
    r = verify(client, TEST_PHONE, TEST_CODE)
    assert r.status_code == 400 and error_code(r) == "CODE_EXPIRED"


def test_other_phones_get_real_sms_and_secret_code_does_not_work(client, sms):
    client.post(f"{API}/auth/phone/request-code", json={"phone": REAL_PHONE})
    assert sms.last_text(REAL_PHONE)
    real_code = sms.last_text(REAL_PHONE).split("код входа ")[1][:4]
    if real_code != TEST_CODE:
        r = verify(client, REAL_PHONE, TEST_CODE)
        assert r.status_code == 400 and error_code(r) == "CODE_INVALID"
    assert verify(client, REAL_PHONE, real_code).status_code == 200
