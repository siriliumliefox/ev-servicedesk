"""Аутентификация и RBAC API (Глава 10, ADR 0013).

Каждый защищённый маршрут объявляет роли через `require_roles(...)` — это и проверка
(401 без/с негодным токеном, 403 при чужой роли), и `x-required-roles` в сгенерированном
OpenAPI. Тест `tests/api/test_rbac_contract.py` требует роли у каждого непубличного маршрута
и сверяет их с docs/openapi.yaml (deny by default). Object-level проверки — в сервисах.
"""

from collections.abc import Callable
from typing import Annotated, Any

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from redis import Redis
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.core.db import SessionScope, get_db, get_session_scope
from app.core.errors import forbidden, unauthorized
from app.core.redis import get_redis
from app.core.security import InvalidTokenError, decode_access_token
from app.core.storage import ObjectStorage, get_storage
from app.domain.auth.sms import SmsProvider, get_sms_provider_for
from app.domain.vehicles.vin import MockVinDecoder, VinDecoder
from app.models import AppUser
from app.models.enums import UserRole

_bearer = HTTPBearer(auto_error=False, bearerFormat="JWT")

SettingsDep = Annotated[Settings, Depends(get_settings)]
DbDep = Annotated[Session, Depends(get_db)]
SessionScopeDep = Annotated[SessionScope, Depends(get_session_scope)]
RedisDep = Annotated[Redis, Depends(get_redis)]
StorageDep = Annotated[ObjectStorage, Depends(get_storage)]


def get_sms_provider(settings: SettingsDep) -> SmsProvider:
    return get_sms_provider_for(settings)


SmsDep = Annotated[SmsProvider, Depends(get_sms_provider)]


def get_vin_decoder() -> VinDecoder:
    """Seam декодера: внешний API (X-05) подключается здесь, тесты подменяют зависимость."""
    return MockVinDecoder()


VinDecoderDep = Annotated[VinDecoder, Depends(get_vin_decoder)]


def client_ip(request: Request) -> str:
    # За обратным прокси uvicorn нужен --forwarded-allow-ips=<IP/CIDR прокси> (или
    # FORWARDED_ALLOW_IPS): иначе X-Forwarded-For игнорируется и лимит по IP считается
    # по адресу прокси. '*' — только если приложение недоступно напрямую (Глава 26).
    return request.client.host if request.client else "unknown"


def get_current_user(
    db: DbDep,
    settings: SettingsDep,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
) -> AppUser:
    """Пользователь из access-токена. Роль и активность берутся из БД, не из токена."""
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise unauthorized()
    try:
        claims = decode_access_token(credentials.credentials, settings)
    except InvalidTokenError as exc:
        raise unauthorized("Недействительный или просроченный токен") from exc
    user = db.get(AppUser, claims.user_id)
    if user is None or not user.is_active or user.anonymized_at is not None:
        raise unauthorized("Учётная запись недоступна")
    return user


CurrentUser = Annotated[AppUser, Depends(get_current_user)]


def require_roles(*roles: UserRole) -> Callable[..., AppUser]:
    allowed = frozenset(roles)

    def dependency(user: CurrentUser) -> AppUser:
        if user.role not in allowed:
            raise forbidden()
        return user

    dependency.required_roles = sorted(r.value for r in allowed)  # type: ignore[attr-defined]
    return dependency


ALL_ROLES = (UserRole.CLIENT, UserRole.ENGINEER, UserRole.ADMIN)


def rbac(*roles: UserRole) -> dict[str, Any]:
    """Параметры маршрута: зависимость RBAC + x-required-roles в OpenAPI."""
    return {
        "dependencies": [Depends(require_roles(*roles))],
        "openapi_extra": {"x-required-roles": sorted(r.value for r in roles)},
    }
