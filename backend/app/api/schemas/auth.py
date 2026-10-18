"""Схемы Auth Service и пользователя — по components/schemas docs/openapi.yaml (ADR 0007).

Серверные границы строже контракта там, где их диктует БД или формат (код 4–8 цифр,
telegram_id ≤ 50 = VARCHAR(50), без управляющих символов) — нарушение даёт объявленный
422; перечислены в описаниях операций контракта и в ADR 0013.
"""

from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.api.pagination import PaginationMeta
from app.api.schemas.common import no_control_chars
from app.models.enums import UserRole

# PhoneE164 контракта; совпадает с CHECK phone_e164 в app_user.
PhoneE164 = Annotated[str, Field(pattern=r"^\+[1-9][0-9]{7,14}$", examples=["+375291234567"])]


class PhoneRequestCode(BaseModel):
    phone: PhoneE164


class RequestCodeResponse(BaseModel):
    ttl_seconds: int


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
        value = no_control_chars(value.strip())
        return value or None


class RefreshRequest(BaseModel):
    refresh_token: Annotated[str, Field(min_length=1, max_length=512)]


class StaffLoginRequest(BaseModel):
    phone: PhoneE164
    password: Annotated[str, Field(min_length=1, max_length=256)]


class TelegramLinkRequest(BaseModel):
    """Данные Telegram Login Widget (ADR 0029 п. 16): `telegram_id` — поле `id` виджета.

    `auth_date` и `hash` в схеме контракта необязательны (аддитивно, ADR 0007), но сервер без
    них отвечает 422: без подписи владение аккаунтом Telegram не доказано.
    """

    telegram_id: Annotated[str, Field(min_length=1, max_length=50, pattern=r"^[0-9]+$")]
    auth_date: Annotated[int | None, Field(ge=0)] = None
    hash: Annotated[str | None, Field(pattern=r"^[0-9a-f]{64}$")] = None
    first_name: Annotated[str | None, Field(max_length=256)] = None
    last_name: Annotated[str | None, Field(max_length=256)] = None
    username: Annotated[str | None, Field(max_length=64)] = None
    photo_url: Annotated[str | None, Field(max_length=1024)] = None

    @field_validator("first_name", "last_name", "username", "photo_url")
    @classmethod
    def _check_text(cls, value: str | None) -> str | None:
        return None if value is None else no_control_chars(value)

    def widget_fields(self) -> dict[str, str]:
        """Полученные поля виджета (кроме подписи) под именами Telegram: `telegram_id` — `id`."""
        fields = self.model_dump(exclude={"telegram_id", "hash"}, exclude_none=True)
        return {"id": self.telegram_id, **{key: str(value) for key, value in fields.items()}}


class StaffPasswordChangeRequest(BaseModel):
    current_password: Annotated[str, Field(min_length=1, max_length=256)]
    new_password: Annotated[str, Field(min_length=12, max_length=128)]


class UserPublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    phone: str | None
    role: UserRole
    is_active: bool
    telegram_id: str | None = None
    created_at: datetime


class UserList(BaseModel):
    items: list[UserPublic]
    meta: PaginationMeta


class StaffUserCreateRequest(BaseModel):
    phone: PhoneE164
    role: Literal[UserRole.ENGINEER, UserRole.ADMIN]
    password: Annotated[str, Field(min_length=12, max_length=128)]


class UserPasswordResetRequest(BaseModel):
    password: Annotated[str, Field(min_length=12, max_length=128)]


class UserUpdateRequest(BaseModel):
    """minProperties: 1 контракта — пустое тело (или только null) отклоняется с 422."""

    role: Literal[UserRole.ENGINEER, UserRole.ADMIN] | None = None
    is_active: bool | None = None

    @model_validator(mode="after")
    def _not_empty(self) -> "UserUpdateRequest":
        if self.role is None and self.is_active is None:
            raise ValueError("Нужно указать role или is_active")
        return self


class AuthTokens(BaseModel):
    access_token: str
    refresh_token: str
    expires_in: int


class StaffLoginResponse(AuthTokens):
    user: UserPublic


class VerifyCodeResponse(AuthTokens):
    is_new_user: bool
    user: UserPublic
