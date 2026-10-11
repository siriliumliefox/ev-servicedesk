"""Unit: SMS-коды в Redis — хранение, валидация, истечение TTL, лимиты (ADR 0005, N-06)."""

import time

import fakeredis
import pytest

from app.core.config import Settings
from app.core.errors import ApiError
from app.domain.auth import codes
from app.domain.auth.sms import FakeSmsProvider, SmsError

PHONE = "+375291234567"
IP = "10.0.0.1"


@pytest.fixture
def redis():
    return fakeredis.FakeRedis(decode_responses=True)


@pytest.fixture
def sms():
    return FakeSmsProvider()


def make_settings(**overrides) -> Settings:
    return Settings(environment="test", **overrides)


def sent_code(sms: FakeSmsProvider, phone: str = PHONE) -> str:
    text = sms.last_text(phone)
    assert text is not None
    return next(w.strip(".") for w in text.split() if w.strip(".").isdigit())


def test_code_stored_as_hmac_with_ttl(redis, sms):
    settings = make_settings()
    ttl = codes.request_code(redis, sms, settings, PHONE, IP)
    assert ttl == settings.sms_code_ttl_seconds
    code = sent_code(sms)
    assert len(code) == settings.sms_code_length
    stored = redis.hgetall(codes.code_key(PHONE))
    assert stored["attempts"] == "0"
    assert stored["h"] != code and code not in stored["h"]
    assert 0 < redis.ttl(codes.code_key(PHONE)) <= settings.sms_code_ttl_seconds
    # Код нигде в Redis не лежит открытым.
    for key in redis.keys("*"):
        value = redis.hgetall(key) if redis.type(key) == "hash" else {"v": redis.get(key)}
        assert all(v != code for v in value.values())


def test_correct_code_ok_and_single_use(redis, sms):
    settings = make_settings()
    codes.request_code(redis, sms, settings, PHONE, IP)
    code = sent_code(sms)
    assert codes.check_code(redis, settings, PHONE, code).status is codes.CodeCheck.OK
    assert codes.consume_code(redis, PHONE) is True
    assert codes.consume_code(redis, PHONE) is False
    assert codes.check_code(redis, settings, PHONE, code).status is codes.CodeCheck.MISSING


def test_wrong_code_counts_attempts(redis, sms):
    settings = make_settings()
    codes.request_code(redis, sms, settings, PHONE, IP)
    code = sent_code(sms)
    wrong = "0000" if code != "0000" else "1111"
    result = codes.check_code(redis, settings, PHONE, wrong)
    assert result.status is codes.CodeCheck.WRONG
    assert result.attempts_left == settings.sms_code_max_attempts - 1


def test_code_burns_after_max_attempts(redis, sms):
    settings = make_settings(sms_code_max_attempts=3)
    codes.request_code(redis, sms, settings, PHONE, IP)
    code = sent_code(sms)
    wrong = "0000" if code != "0000" else "1111"
    for _ in range(2):
        assert codes.check_code(redis, settings, PHONE, wrong).status is codes.CodeCheck.WRONG
    with pytest.raises(ApiError) as exc:
        codes.check_code(redis, settings, PHONE, wrong)
    assert exc.value.status_code == 429
    # Даже верный код после исчерпания попыток не принимается.
    assert codes.check_code(redis, settings, PHONE, code).status is codes.CodeCheck.MISSING


def test_code_expires_after_ttl(redis, sms):
    settings = make_settings(sms_code_ttl_seconds=1)
    codes.request_code(redis, sms, settings, PHONE, IP)
    code = sent_code(sms)
    time.sleep(1.2)
    assert codes.check_code(redis, settings, PHONE, code).status is codes.CodeCheck.MISSING


def test_unrequested_code_missing(redis):
    result = codes.check_code(redis, make_settings(), PHONE, "1234")
    assert result.status is codes.CodeCheck.MISSING


def test_new_code_replaces_old(redis, sms):
    settings = make_settings(sms_resend_cooldown_seconds=1)
    codes.request_code(redis, sms, settings, PHONE, IP)
    first = sent_code(sms)
    time.sleep(1.1)
    codes.request_code(redis, sms, settings, PHONE, IP)
    second = sent_code(sms)
    if first != second:
        assert codes.check_code(redis, settings, PHONE, first).status is codes.CodeCheck.WRONG
    assert codes.check_code(redis, settings, PHONE, second).status is codes.CodeCheck.OK


def test_resend_cooldown(redis, sms):
    settings = make_settings()
    codes.request_code(redis, sms, settings, PHONE, IP)
    with pytest.raises(ApiError) as exc:
        codes.request_code(redis, sms, settings, PHONE, IP)
    assert exc.value.status_code == 429
    retry = int(exc.value.headers["Retry-After"])
    assert 0 < retry <= settings.sms_resend_cooldown_seconds
    assert sms.sent_count == 1


def test_hourly_limit_per_phone(redis, sms):
    settings = make_settings(sms_resend_cooldown_seconds=1, sms_requests_per_phone_hour=2)
    for _ in range(2):
        codes.request_code(redis, sms, settings, PHONE, IP)
        redis.delete("auth:rl:sms-cooldown:" + PHONE)
    with pytest.raises(ApiError) as exc:
        codes.request_code(redis, sms, settings, PHONE, IP)
    assert exc.value.status_code == 429
    assert sms.sent_count == 2


def test_hourly_limit_per_ip(redis, sms):
    settings = make_settings(sms_requests_per_ip_hour=3)
    for i in range(3):
        codes.request_code(redis, sms, settings, f"+37529100000{i}", IP)
    with pytest.raises(ApiError) as exc:
        codes.request_code(redis, sms, settings, "+375291000009", IP)
    assert exc.value.status_code == 429
    # Другой адрес не затронут.
    codes.request_code(redis, sms, settings, "+375291000009", "10.0.0.2")


def test_daily_failure_limit(redis, sms):
    settings = make_settings(verify_failures_per_phone_day=2, sms_code_max_attempts=10)
    codes.request_code(redis, sms, settings, PHONE, IP)
    code = sent_code(sms)
    wrong = "0000" if code != "0000" else "1111"
    for _ in range(2):
        codes.check_code(redis, settings, PHONE, wrong)
    with pytest.raises(ApiError) as exc:
        codes.check_code(redis, settings, PHONE, code)
    assert exc.value.status_code == 429


class BrokenSms:
    def __init__(self, invalid_recipient: bool = False) -> None:
        self.invalid_recipient = invalid_recipient

    def send(self, phone: str, text: str) -> None:
        raise SmsError("down", invalid_recipient=self.invalid_recipient)


@pytest.mark.parametrize(("invalid", "status"), [(False, 503), (True, 422)])
def test_sms_failure_removes_code(redis, invalid, status):
    with pytest.raises(ApiError) as exc:
        codes.request_code(redis, BrokenSms(invalid), make_settings(), PHONE, IP)
    assert exc.value.status_code == status
    assert not redis.exists(codes.code_key(PHONE))


def test_sms_text_contains_no_extra_digits():
    # Отладочный эндпоинт ищет первое число в тексте — в шаблоне других чисел быть не должно.
    assert not any(ch.isdigit() for ch in codes.SMS_TEXT.replace("{code}", ""))
