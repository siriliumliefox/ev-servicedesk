"""Unit: SMS-коды в Redis — хранение, валидация, истечение TTL, лимиты (ADR 0005, N-06)."""

import time

import fakeredis
import pytest

from app.core.config import Settings
from app.core.errors import ApiError
from app.core.security import hash_sms_code
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
    return Settings(_env_file=None, environment="test", **overrides)


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
    # Хранится HMAC (64 hex), а не код.
    assert stored["h"] == hash_sms_code(PHONE, code, settings) and stored["h"] != code
    assert 0 < redis.ttl(codes.code_key(PHONE)) <= settings.sms_code_ttl_seconds
    # Код нигде в Redis не лежит открытым.
    for key in redis.keys("*"):
        value = redis.hgetall(key) if redis.type(key) == "hash" else {"v": redis.get(key)}
        assert all(v != code for v in value.values())


def test_correct_code_ok_and_single_use(redis, sms):
    settings = make_settings()
    codes.request_code(redis, sms, settings, PHONE, IP)
    code = sent_code(sms)
    result = codes.check_code(redis, settings, PHONE, code)
    assert result.status is codes.CodeCheck.OK
    # Верный код не тратит попытку (может понадобиться после 422 PD_CONSENT_REQUIRED).
    assert redis.hget(codes.code_key(PHONE), "attempts") == "0"
    assert codes.consume_code(redis, PHONE, result.code_hash) is True
    assert codes.consume_code(redis, PHONE, result.code_hash) is False
    assert codes.check_code(redis, settings, PHONE, code).status is codes.CodeCheck.MISSING


def test_consume_deletes_only_the_verified_code(redis, sms):
    """Проверенный старый код не «съедает» выпущенный следом новый (compare-and-delete)."""
    settings = make_settings()
    codes.request_code(redis, sms, settings, PHONE, IP)
    old = codes.check_code(redis, settings, PHONE, sent_code(sms))
    redis.hset(codes.code_key(PHONE), "h", "f" * 64)  # тем временем выпущен другой код
    assert codes.consume_code(redis, PHONE, old.code_hash) is False
    assert redis.exists(codes.code_key(PHONE))


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
    settings = make_settings()
    codes.request_code(redis, sms, settings, PHONE, IP)
    code = sent_code(sms)
    redis.pexpire(codes.code_key(PHONE), 50)  # TTL истекает (минимальный TTL настроек — 30 с)
    time.sleep(0.2)
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
    def __init__(self, invalid_recipient: bool = False, delivery_unknown: bool = False) -> None:
        self.invalid_recipient = invalid_recipient
        self.delivery_unknown = delivery_unknown

    def send(self, phone: str, text: str) -> None:
        raise SmsError(
            "down", invalid_recipient=self.invalid_recipient, delivery_unknown=self.delivery_unknown
        )


@pytest.mark.parametrize(("invalid", "status"), [(False, 503), (True, 422)])
def test_sms_not_sent_removes_code_and_returns_limits(redis, invalid, status):
    settings = make_settings()
    with pytest.raises(ApiError) as exc:
        codes.request_code(redis, BrokenSms(invalid), settings, PHONE, IP)
    assert exc.value.status_code == status
    assert not redis.exists(codes.code_key(PHONE))
    # SMS точно не ушло — пауза и лимит номера не потрачены: можно сразу повторить.
    assert not redis.exists("auth:rl:sms-cooldown:" + PHONE)
    assert redis.get("auth:rl:sms-phone:" + PHONE) == "0"
    sms = FakeSmsProvider()
    codes.request_code(redis, sms, settings, PHONE, IP)
    assert sms.sent_count == 1


def test_sms_delivery_unknown_keeps_code_and_cooldown(redis):
    """Таймаут ответа A1: SMS могло дойти — код действует, повтор только после паузы."""
    settings = make_settings()
    with pytest.raises(ApiError) as exc:
        codes.request_code(redis, BrokenSms(delivery_unknown=True), settings, PHONE, IP)
    assert exc.value.status_code == 503
    assert redis.exists(codes.code_key(PHONE))
    with pytest.raises(ApiError) as again:
        codes.request_code(redis, FakeSmsProvider(), settings, PHONE, IP)
    assert again.value.status_code == 429


def test_sms_text_contains_no_extra_digits():
    # Отладочный эндпоинт ищет первое число в тексте — в шаблоне других чисел быть не должно.
    assert not any(ch.isdigit() for ch in codes.SMS_TEXT.replace("{code}", ""))


def test_refund_does_not_touch_code_issued_during_check(redis, sms, monkeypatch):
    """Возврат попытки — только проверенному коду, не выпущенному в этот момент новому."""
    settings = make_settings()
    codes.request_code(redis, sms, settings, PHONE, IP)
    code = sent_code(sms)
    original = codes.sms_code_matches

    def reissue_during_compare(*args, **kwargs):
        redis.hset(codes.code_key(PHONE), mapping={"h": "e" * 64, "attempts": 0})
        return original(*args, **kwargs)

    monkeypatch.setattr(codes, "sms_code_matches", reissue_during_compare)
    assert codes.check_code(redis, settings, PHONE, code).status is codes.CodeCheck.OK
    assert redis.hget(codes.code_key(PHONE), "attempts") == "0"  # не -1


def test_burn_does_not_delete_code_issued_during_check(redis, sms, monkeypatch):
    settings = make_settings(sms_code_max_attempts=1)
    codes.request_code(redis, sms, settings, PHONE, IP)
    code = sent_code(sms)
    original = codes.sms_code_matches

    def reissue_during_compare(*args, **kwargs):
        redis.hset(codes.code_key(PHONE), mapping={"h": "e" * 64, "attempts": 0})
        return original(*args, **kwargs)

    monkeypatch.setattr(codes, "sms_code_matches", reissue_during_compare)
    with pytest.raises(ApiError):
        codes.check_code(redis, settings, PHONE, "0000" if code != "0000" else "1111")
    assert redis.hget(codes.code_key(PHONE), "h") == "e" * 64
