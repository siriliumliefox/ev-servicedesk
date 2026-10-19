"""Auth Service — пути `/auth/*` контракта (docs/openapi.yaml, тег Auth)."""

import asyncio
from functools import partial
from typing import Annotated, Literal
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
    StaffPasswordChangeRequest,
    TelegramLinkRequest,
    UserPublic,
    VerifyCodeRequest,
    VerifyCodeResponse,
)
from app.core.audit import security_event
from app.core.errors import ApiError
from app.domain.auth import service, sessions, staff, telegram, tokens
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


def _outcome(exc: ApiError) -> Literal["failure", "denied"]:
    """429 — отказ лимитом попыток (подбор), остальное — неудача."""
    return "denied" if exc.status_code == status.HTTP_429_TOO_MANY_REQUESTS else "failure"


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
    body: VerifyCodeRequest, db: DbDep, redis: RedisDep, settings: SettingsDep, ip: ClientIp
) -> VerifyCodeResponse:
    try:
        result = service.verify_phone_code(
            db, redis, settings, body.phone, body.code, body.pd_policy_version
        )
    except ApiError as exc:
        # Номер в журнал не пишется: только IP и код ответа (подбор кода виден по IP).
        security_event("auth.client_login", outcome=_outcome(exc), ip=ip, target=exc.code)
        raise
    event = "auth.client_registered" if result.is_new_user else "auth.client_login"
    security_event(event, user_id=result.user.id, role=result.user.role.value, ip=ip)
    return VerifyCodeResponse(
        **vars(result.tokens),
        is_new_user=result.is_new_user,
        user=UserPublic.model_validate(result.user),
    )


@router.post("/refresh", operation_id="refreshToken")
def refresh_token(body: RefreshRequest, db: DbDep, settings: SettingsDep) -> AuthTokens:
    return AuthTokens(**vars(tokens.rotate(db, body.refresh_token, settings)))


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
    sessions.revoke_token(redis, claims)
    security_event("auth.logout", user_id=user.id, role=user.role.value)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.delete(
    "/pd-consent",
    operation_id="withdrawPdConsent",
    status_code=status.HTTP_202_ACCEPTED,
    response_class=Response,
    **rbac(UserRole.CLIENT),
)
def withdraw_pd_consent(user: CurrentUser, db: DbDep) -> Response:
    service.withdraw_pd_consent(db, user)
    security_event("pd.consent_withdrawn", user_id=user.id, role=user.role.value)
    return Response(status_code=status.HTTP_202_ACCEPTED)


@router.post("/staff/login", operation_id="staffLogin")
def staff_login(
    body: StaffLoginRequest, db: DbDep, redis: RedisDep, settings: SettingsDep, ip: ClientIp
) -> StaffLoginResponse:
    try:
        result = staff.login(db, redis, settings, body.phone, body.password, ip)
    except ApiError as exc:
        security_event("auth.staff_login", outcome=_outcome(exc), ip=ip, target=exc.code)
        raise
    security_event("auth.staff_login", user_id=result.user.id, role=result.user.role.value, ip=ip)
    return StaffLoginResponse(**vars(result.tokens), user=UserPublic.model_validate(result.user))


@router.post(
    "/staff/password", operation_id="changeStaffPassword", **rbac(UserRole.ENGINEER, UserRole.ADMIN)
)
def change_staff_password(
    body: StaffPasswordChangeRequest,
    user: CurrentUser,
    db: DbDep,
    redis: RedisDep,
    settings: SettingsDep,
    ip: ClientIp,
) -> AuthTokens:
    try:
        pair = staff.change_password(
            db, redis, settings, user, body.current_password, body.new_password, ip
        )
    except ApiError as exc:
        security_event(
            "auth.password_changed",
            outcome=_outcome(exc),
            user_id=user.id,
            role=user.role.value,
            ip=ip,
            target=exc.code,
        )
        raise
    security_event("auth.password_changed", user_id=user.id, role=user.role.value, ip=ip)
    return AuthTokens(**vars(pair))


@router.post("/telegram/link", operation_id="linkTelegram", **rbac(UserRole.CLIENT))
def link_telegram(
    body: TelegramLinkRequest, user: CurrentUser, db: DbDep, settings: SettingsDep
) -> UserPublic:
    telegram_id = telegram.verify_widget(settings, body.widget_fields(), body.hash)
    return UserPublic.model_validate(service.link_telegram(db, user, telegram_id))
