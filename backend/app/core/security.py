"""Криптопримитивы Auth Service (ADR 0005, 0013): JWT, refresh-токены, SMS-коды, пароли."""

import hashlib
import hmac
import secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError

from app.core.config import Settings

JWT_ALGORITHM = "HS256"
ACCESS_TOKEN_TYPE = "access"

_password_hasher = PasswordHasher()
# Хэш для выравнивания времени ответа, когда пользователя нет (не раскрываем существование).
_DUMMY_PASSWORD_HASH = _password_hasher.hash("dummy-password-for-timing")


class InvalidTokenError(Exception):
    """Access-токен отсутствует, подделан, просрочен или не того типа."""


@dataclass(frozen=True)
class AccessClaims:
    user_id: int
    role: str
    expires_at: datetime


def create_access_token(
    user_id: int, role: str, settings: Settings, now: datetime | None = None
) -> str:
    now = now or datetime.now(UTC)
    payload = {
        "sub": str(user_id),
        "role": role,
        "typ": ACCESS_TOKEN_TYPE,
        "iss": settings.jwt_issuer,
        "aud": settings.jwt_audience,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(seconds=settings.access_token_ttl_seconds)).timestamp()),
        "jti": uuid.uuid4().hex,
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=JWT_ALGORITHM)


def decode_access_token(token: str, settings: Settings) -> AccessClaims:
    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret,
            algorithms=[JWT_ALGORITHM],  # фиксированный алгоритм: защита от alg=none/подмены
            audience=settings.jwt_audience,
            issuer=settings.jwt_issuer,
            options={"require": ["sub", "exp", "iat", "typ", "role"]},
        )
    except jwt.PyJWTError as exc:
        raise InvalidTokenError(type(exc).__name__) from exc
    if payload["typ"] != ACCESS_TOKEN_TYPE:
        raise InvalidTokenError("wrong token type")
    try:
        user_id = int(payload["sub"])
    except (TypeError, ValueError) as exc:
        raise InvalidTokenError("bad sub") from exc
    return AccessClaims(
        user_id=user_id,
        role=str(payload["role"]),
        expires_at=datetime.fromtimestamp(payload["exp"], UTC),
    )


def new_refresh_token() -> str:
    """Непрозрачный случайный токен (не JWT): в БД хранится только его SHA-256."""
    return secrets.token_urlsafe(48)


def hash_refresh_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def generate_sms_code(length: int) -> str:
    return "".join(secrets.choice("0123456789") for _ in range(length))


def hash_sms_code(phone: str, code: str, settings: Settings) -> str:
    """HMAC-SHA256(телефон:код): одинаковый код у разных номеров даёт разные хэши."""
    message = f"{phone}:{code}".encode()
    return hmac.new(settings.sms_code_secret.encode(), message, hashlib.sha256).hexdigest()


def sms_code_matches(phone: str, code: str, expected_hash: str, settings: Settings) -> bool:
    return hmac.compare_digest(hash_sms_code(phone, code, settings), expected_hash)


def hash_password(password: str) -> str:
    return _password_hasher.hash(password)


def verify_password(password: str, password_hash: str | None) -> bool:
    """argon2id (N-08). Без хэша всё равно считаем, чтобы время ответа не выдавало пользователя."""
    try:
        return _password_hasher.verify(password_hash or _DUMMY_PASSWORD_HASH, password) and bool(
            password_hash
        )
    except (VerificationError, InvalidHashError):
        return False
