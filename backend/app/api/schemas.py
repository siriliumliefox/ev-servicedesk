"""Pydantic-схемы запросов/ответов — по components/schemas docs/openapi.yaml (ADR 0007).

Серверные границы строже контракта там, где их диктует БД или формат (код 4–8 цифр,
telegram_id ≤ 50 = VARCHAR(50), без управляющих символов) — нарушение даёт объявленный
422; перечислены в описаниях операций контракта и в ADR 0013.
"""

import re
from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models.enums import UserRole

# PhoneE164 контракта; совпадает с CHECK phone_e164 в app_user.
PhoneE164 = Annotated[str, Field(pattern=r"^\+[1-9][0-9]{7,14}$", examples=["+375291234567"])]


class PhoneRequestCode(BaseModel):
    phone: PhoneE164


class RequestCodeResponse(BaseModel):
    ttl_seconds: int


_CONTROL = re.compile(r"[\x00-\x1f\x7f]")


def _no_control_chars(value: str) -> str:
    # PostgreSQL не хранит NUL в text: без проверки — 500 вместо 422.
    if _CONTROL.search(value):
        raise ValueError("управляющие символы недопустимы")
    return value


class VerifyCodeRequest(BaseModel):
    phone: PhoneE164
    code: Annotated[str, Field(pattern=r"^[0-9]{4,8}$", examples=["1234"])]
    pd_policy_version: Annotated[str | None, Field(max_length=20)] = None

    @field_validator("pd_policy_version")
    @classmethod
    def _policy_version(cls, value: str | None) -> str | None:
        """Пробелы по краям отбрасываются; пустая строка = согласие не передано."""
        if value is None:
            return None
        value = _no_control_chars(value.strip())
        return value or None


class RefreshRequest(BaseModel):
    refresh_token: Annotated[str, Field(min_length=1, max_length=512)]


class StaffLoginRequest(BaseModel):
    phone: PhoneE164
    password: Annotated[str, Field(min_length=1, max_length=256)]


class TelegramLinkRequest(BaseModel):
    telegram_id: Annotated[str, Field(min_length=1, max_length=50)]

    _check_telegram_id = field_validator("telegram_id")(_no_control_chars)


class UserPublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    phone: str | None
    role: UserRole
    is_active: bool
    telegram_id: str | None = None
    created_at: datetime


class AuthTokens(BaseModel):
    access_token: str
    refresh_token: str
    expires_in: int


class StaffLoginResponse(AuthTokens):
    user: UserPublic


class VerifyCodeResponse(AuthTokens):
    is_new_user: bool
    user: UserPublic
