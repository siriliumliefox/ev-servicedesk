"""Unit: генерация и проверка токенов, хэши, пароли, настройки окружений (Глава 10)."""

import base64
import json
from datetime import UTC, datetime, timedelta

import jwt
import pytest
from pydantic import ValidationError

from app.core import security
from app.core.config import Settings

SETTINGS = Settings(_env_file=None, environment="test", jwt_secret="unit-test-secret-" + "x" * 32)


def test_access_token_roundtrip():
    token = security.create_access_token(42, "engineer", SETTINGS)
    claims = security.decode_access_token(token, SETTINGS)
    assert claims.user_id == 42
    assert claims.role == "engineer"
    ttl = (claims.expires_at - datetime.now(UTC)).total_seconds()
    assert SETTINGS.access_token_ttl_seconds - 5 <= ttl <= SETTINGS.access_token_ttl_seconds


def test_access_tokens_are_unique():
    assert security.create_access_token(1, "client", SETTINGS) != security.create_access_token(
        1, "client", SETTINGS
    )


def test_expired_access_token_rejected():
    past = datetime.now(UTC) - timedelta(seconds=SETTINGS.access_token_ttl_seconds + 1)
    token = security.create_access_token(1, "client", SETTINGS, now=past)
    with pytest.raises(security.InvalidTokenError):
        security.decode_access_token(token, SETTINGS)


def test_token_signed_with_other_secret_rejected():
    other = Settings(_env_file=None, environment="test", jwt_secret="another-secret-" + "y" * 32)
    token = security.create_access_token(1, "admin", other)
    with pytest.raises(security.InvalidTokenError):
        security.decode_access_token(token, SETTINGS)


def _b64(data: dict) -> str:
    return base64.urlsafe_b64encode(json.dumps(data).encode()).rstrip(b"=").decode()


def test_alg_none_rejected():
    now = int(datetime.now(UTC).timestamp())
    payload = {
        "sub": "1",
        "role": "admin",
        "typ": "access",
        "iss": SETTINGS.jwt_issuer,
        "aud": SETTINGS.jwt_audience,
        "iat": now,
        "exp": now + 600,
    }
    token = f"{_b64({'alg': 'none', 'typ': 'JWT'})}.{_b64(payload)}."
    with pytest.raises(security.InvalidTokenError):
        security.decode_access_token(token, SETTINGS)


def test_tampered_payload_rejected():
    token = security.create_access_token(1, "client", SETTINGS)
    header, payload, signature = token.split(".")
    data = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
    data["role"] = "admin"
    with pytest.raises(security.InvalidTokenError):
        security.decode_access_token(f"{header}.{_b64(data)}.{signature}", SETTINGS)


@pytest.mark.parametrize(
    "override",
    [
        {"typ": "refresh"},
        {"aud": "someone-else"},
        {"iss": "someone-else"},
        {"sub": "not-a-number"},
    ],
)
def test_wrong_claims_rejected(override):
    now = int(datetime.now(UTC).timestamp())
    payload = {
        "sub": "1",
        "role": "client",
        "typ": "access",
        "iss": SETTINGS.jwt_issuer,
        "aud": SETTINGS.jwt_audience,
        "iat": now,
        "exp": now + 600,
    } | override
    token = jwt.encode(payload, SETTINGS.jwt_secret, algorithm="HS256")
    with pytest.raises(security.InvalidTokenError):
        security.decode_access_token(token, SETTINGS)


def test_missing_claim_rejected():
    now = int(datetime.now(UTC).timestamp())
    token = jwt.encode(
        {"sub": "1", "aud": SETTINGS.jwt_audience, "iss": SETTINGS.jwt_issuer, "exp": now + 60},
        SETTINGS.jwt_secret,
        algorithm="HS256",
    )
    with pytest.raises(security.InvalidTokenError):
        security.decode_access_token(token, SETTINGS)


def test_refresh_token_random_and_hashed_sha256():
    a, b = security.new_refresh_token(), security.new_refresh_token()
    assert a != b and len(a) >= 64
    digest = security.hash_refresh_token(a)
    assert len(digest) == 64 and all(c in "0123456789abcdef" for c in digest)
    assert a not in digest


def test_sms_code_format_and_hmac():
    code = security.generate_sms_code(4)
    assert len(code) == 4 and code.isdigit()
    h = security.hash_sms_code("+375291234567", code, SETTINGS)
    assert h != code and len(h) == 64 and all(c in "0123456789abcdef" for c in h)
    assert security.sms_code_matches("+375291234567", code, h, SETTINGS)
    # Тот же код другого номера и неверный код не совпадают.
    assert not security.sms_code_matches("+375291234568", code, h, SETTINGS)
    wrong = "0000" if code != "0000" else "1111"
    assert not security.sms_code_matches("+375291234567", wrong, h, SETTINGS)


def test_sms_codes_are_distributed():
    codes = {security.generate_sms_code(4) for _ in range(500)}
    assert len(codes) > 300  # из 10 000 вариантов повторы редки


def test_password_hash_argon2():
    h = security.hash_password("s3cret-pass")
    assert h.startswith("$argon2id$")
    assert security.verify_password("s3cret-pass", h)
    assert not security.verify_password("wrong", h)
    assert not security.verify_password("anything", None)
    assert not security.verify_password("anything", "not-a-hash")


def test_real_environment_rejects_default_secrets():
    with pytest.raises(ValidationError, match="JWT_SECRET"):
        Settings(_env_file=None, environment="staging")


def test_production_rejects_fake_sms_provider():
    strong = "z" * 40
    with pytest.raises(ValidationError, match="SMS_PROVIDER=fake"):
        Settings(
            _env_file=None, environment="production", jwt_secret=strong, sms_code_secret=strong
        )


def test_a1_requires_credentials():
    strong = "z" * 40
    with pytest.raises(ValidationError, match="SMS_PROVIDER_USER"):
        Settings(
            _env_file=None,
            environment="staging",
            jwt_secret=strong,
            sms_code_secret=strong,
            sms_provider="a1",
        )


def test_staging_with_real_secrets_ok():
    strong = "z" * 40
    s = Settings(
        _env_file=None,
        environment="staging",
        jwt_secret=strong,
        sms_code_secret=strong,
        s3_access_key="staging-access-key",  # ключи S3 обязательны вне local/test (ADR 0017)
        s3_secret_key=strong,
    )
    assert s.sms_provider == "fake"


def test_settings_reject_unknown_environment():
    with pytest.raises(ValidationError):
        Settings(_env_file=None, environment="prod")


@pytest.mark.parametrize(
    "override",
    [
        {"sms_provider_rps": 0},
        {"sms_provider_rps": 11},
        {"sms_code_length": 3},
        {"sms_code_length": 9},
        {"sms_sender": "TOO-LONG-NAME"},
        {"sms_code_max_attempts": 0},
    ],
)
def test_settings_reject_out_of_range(override):
    with pytest.raises(ValidationError):
        Settings(_env_file=None, environment="test", **override)


def test_validation_error_hides_secret_values():
    """Ошибка старта перечисляет имена переменных, но не их значения."""
    secret = "short-leaky-secret"  # < 32 символов — отклоняется
    with pytest.raises(ValidationError) as exc:
        Settings(_env_file=None, environment="staging", jwt_secret=secret)
    assert secret not in str(exc.value)
    assert "JWT_SECRET" in str(exc.value)
