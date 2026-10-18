"""Auth Service — пути `/auth/*` контракта (docs/openapi.yaml, тег Auth)."""

import asyncio
from functools import partial
from typing import Annotated
from weakref import WeakKeyDictionary

import anyio
from fastapi import APIRouter, Depends, Response, status

from app.api.deps import (
    ALL_ROLES,
    AccessClaimsDep,
    CurrentUser,
    DbDep,
    RedisDep,
    SettingsDep,
    SmsDep,
    client_ip,
    rbac,
)
from app.api.schemas.auth import (
    AuthTokens,
    PhoneRequestCode,
    RefreshRequest,
    RequestCodeResponse,
    StaffLoginRequest,
    StaffLoginResponse,
    TelegramLinkRequest,
    UserPublic,
    VerifyCodeRequest,
    VerifyCodeResponse,
)
from app.domain.auth import revocation, service, tokens
from app.models.enums import UserRole

router = APIRouter(prefix="/auth", tags=["Auth"])
ClientIp = Annotated[str, Depends(client_ip)]

# Отправка SMS ждёт провайдера (очередь 10 запросов/с, сеть) — в отдельном пуле потоков,
# чтобы медленный A1 не занял общий пул остальных эндпоинтов (ADR 0013). Лимитер
# привязан к циклу событий, поэтому создаётся на каждый цикл.
SMS_THREADS = 50
_sms_limiters: WeakKeyDictionary[asyncio.AbstractEventLoop, anyio.CapacityLimiter] = (
    WeakKeyDictionary()
)


def _sms_limiter() -> anyio.CapacityLimiter:
    loop = asyncio.get_running_loop()
    limiter = _sms_limiters.get(loop)
    if limiter is None:
        limiter = _sms_limiters[loop] = anyio.CapacityLimiter(SMS_THREADS)
    return limiter


@router.post("/phone/request-code", operation_id="requestPhoneCode")
async def request_phone_code(
    body: PhoneRequestCode,
    db: DbDep,
    redis: RedisDep,
    sms: SmsDep,
    settings: SettingsDep,
    ip: ClientIp,
) -> RequestCodeResponse:
    send = partial(service.request_phone_code, db, redis, sms, settings, body.phone, ip)
    ttl = await anyio.to_thread.run_sync(send, limiter=_sms_limiter())
    return RequestCodeResponse(ttl_seconds=ttl)


@router.post("/phone/verify-code", operation_id="verifyPhoneCode")
def verify_phone_code(
    body: VerifyCodeRequest, db: DbDep, redis: RedisDep, settings: SettingsDep
) -> VerifyCodeResponse:
    result = service.verify_phone_code(
        db, redis, settings, body.phone, body.code, body.pd_policy_version
    )
    return VerifyCodeResponse(
        **vars(result.tokens),
        is_new_user=result.is_new_user,
        user=UserPublic.model_validate(result.user),
    )


@router.post("/refresh", operation_id="refreshToken")
def refresh_token(
    body: RefreshRequest, db: DbDep, redis: RedisDep, settings: SettingsDep
) -> AuthTokens:
    return AuthTokens(**vars(tokens.rotate(db, redis, body.refresh_token, settings)))


@router.post(
    "/logout",
    operation_id="logout",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    **rbac(*ALL_ROLES),
)
def logout(
    body: RefreshRequest, user: CurrentUser, claims: AccessClaimsDep, db: DbDep, redis: RedisDep
) -> Response:
    """Выход: refresh-токен (если свой) и предъявленный access-токен (ADR 0029 п. 12)."""
    tokens.revoke(db, body.refresh_token, user.id)
    revocation.revoke_token(redis, claims)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.delete(
    "/pd-consent",
    operation_id="withdrawPdConsent",
    status_code=status.HTTP_202_ACCEPTED,
    response_class=Response,
    **rbac(UserRole.CLIENT),
)
def withdraw_pd_consent(
    user: CurrentUser, db: DbDep, redis: RedisDep, settings: SettingsDep
) -> Response:
    service.withdraw_pd_consent(db, redis, settings, user)
    return Response(status_code=status.HTTP_202_ACCEPTED)


@router.post("/staff/login", operation_id="staffLogin")
def staff_login(
    body: StaffLoginRequest, db: DbDep, redis: RedisDep, settings: SettingsDep, ip: ClientIp
) -> StaffLoginResponse:
    result = service.staff_login(db, redis, settings, body.phone, body.password, ip)
    return StaffLoginResponse(**vars(result.tokens), user=UserPublic.model_validate(result.user))


@router.post("/telegram/link", operation_id="linkTelegram", **rbac(UserRole.CLIENT))
def link_telegram(body: TelegramLinkRequest, user: CurrentUser, db: DbDep) -> UserPublic:
    return UserPublic.model_validate(service.link_telegram(db, user, body.telegram_id))
