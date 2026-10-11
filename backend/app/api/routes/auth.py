"""Auth Service — пути `/auth/*` контракта (docs/openapi.yaml, тег Auth)."""

from typing import Annotated

from fastapi import APIRouter, Depends, Response, status

from app.api.deps import (
    ALL_ROLES,
    CurrentUser,
    DbDep,
    RedisDep,
    SettingsDep,
    SmsDep,
    client_ip,
    rbac,
)
from app.api.schemas import (
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
from app.domain.auth import codes, service, tokens
from app.models.enums import UserRole

router = APIRouter(prefix="/auth", tags=["Auth"])
ClientIp = Annotated[str, Depends(client_ip)]


@router.post("/phone/request-code", operation_id="requestPhoneCode")
def request_phone_code(
    body: PhoneRequestCode, redis: RedisDep, sms: SmsDep, settings: SettingsDep, ip: ClientIp
) -> RequestCodeResponse:
    ttl = codes.request_code(redis, sms, settings, body.phone, ip)
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
def refresh_token(body: RefreshRequest, db: DbDep, settings: SettingsDep) -> AuthTokens:
    return AuthTokens(**vars(tokens.rotate(db, body.refresh_token, settings)))


@router.post(
    "/logout",
    operation_id="logout",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    **rbac(*ALL_ROLES),
)
def logout(body: RefreshRequest, user: CurrentUser, db: DbDep) -> Response:
    tokens.revoke(db, body.refresh_token, user.id)
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
