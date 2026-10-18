"""Users — профиль (`/me`) и управление пользователями (Глава 17, ADR 0021 п. 3; ADR 0026)."""

from typing import Annotated

from fastapi import APIRouter, Path, Query, Response, status

from app.api.deps import ALL_ROLES, CurrentUser, DbDep, RedisDep, rbac
from app.api.pagination import PageDep, paginate
from app.api.schemas.auth import (
    StaffUserCreateRequest,
    UserList,
    UserPasswordResetRequest,
    UserPublic,
    UserUpdateRequest,
)
from app.api.schemas.common import SafeOptionalText
from app.core.audit import security_event
from app.domain.users import service
from app.models.enums import UserRole

router = APIRouter(tags=["Users"])

UserId = Annotated[int, Path(alias="userId")]


@router.get("/me", operation_id="getCurrentUser", **rbac(*ALL_ROLES))
def get_current_user_profile(user: CurrentUser) -> UserPublic:
    return UserPublic.model_validate(user)


@router.get("/users", operation_id="listUsers", **rbac(UserRole.ADMIN))
def list_users(
    db: DbDep,
    page: PageDep,
    role: UserRole | None = None,
    is_active: bool | None = None,
    search: Annotated[str | None, Query(max_length=16), SafeOptionalText] = None,
) -> UserList:
    items, meta = paginate(db, service.list_users_stmt(role, is_active, search), page)
    return UserList(items=items, meta=meta)


@router.post(
    "/users",
    operation_id="createStaffUser",
    status_code=status.HTTP_201_CREATED,
    **rbac(UserRole.ADMIN),
)
def create_staff_user(body: StaffUserCreateRequest, admin: CurrentUser, db: DbDep) -> UserPublic:
    user = service.create_staff_user(db, body.phone, body.role, body.password)
    security_event("user.created", user_id=admin.id, role=user.role.value, target_user_id=user.id)
    return UserPublic.model_validate(user)


@router.get("/users/{userId}", operation_id="getUser", **rbac(UserRole.ADMIN))
def get_user(user_id: UserId, db: DbDep) -> UserPublic:
    return UserPublic.model_validate(service.get_user(db, user_id))


@router.patch("/users/{userId}", operation_id="updateUser", **rbac(UserRole.ADMIN))
def update_user(
    user_id: UserId, body: UserUpdateRequest, admin: CurrentUser, db: DbDep
) -> UserPublic:
    user = service.update_user(db, user_id, body.role, body.is_active)
    if body.role is not None:
        security_event(
            "user.role_changed", user_id=admin.id, role=body.role.value, target_user_id=user_id
        )
    if body.is_active is not None:
        event = "user.unblocked" if body.is_active else "user.blocked"
        security_event(event, user_id=admin.id, target_user_id=user_id)
    return UserPublic.model_validate(user)


@router.post(
    "/users/{userId}/password",
    operation_id="resetUserPassword",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    **rbac(UserRole.ADMIN),
)
def reset_user_password(
    user_id: UserId, body: UserPasswordResetRequest, admin: CurrentUser, db: DbDep, redis: RedisDep
) -> Response:
    service.reset_password(db, redis, user_id, body.password)
    security_event("user.password_reset", user_id=admin.id, target_user_id=user_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
