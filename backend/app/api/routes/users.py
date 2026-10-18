"""Users — профиль (`/me`) и управление пользователями (Глава 17, ADR 0021 п. 3; ADR 0026)."""

from typing import Annotated

from fastapi import APIRouter, Path, Query, Response, status

from app.api.deps import ALL_ROLES, CurrentUser, DbDep, RedisDep, SettingsDep, rbac
from app.api.pagination import PageDep, paginate
from app.api.schemas.auth import (
    StaffUserCreateRequest,
    UserList,
    UserPasswordResetRequest,
    UserPublic,
    UserUpdateRequest,
)
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
    search: Annotated[str | None, Query(max_length=16)] = None,
) -> UserList:
    items, meta = paginate(db, service.list_users_stmt(role, is_active, search), page)
    return UserList(items=items, meta=meta)


@router.post(
    "/users",
    operation_id="createStaffUser",
    status_code=status.HTTP_201_CREATED,
    **rbac(UserRole.ADMIN),
)
def create_staff_user(body: StaffUserCreateRequest, db: DbDep) -> UserPublic:
    user = service.create_staff_user(db, body.phone, body.role, body.password)
    return UserPublic.model_validate(user)


@router.get("/users/{userId}", operation_id="getUser", **rbac(UserRole.ADMIN))
def get_user(user_id: UserId, db: DbDep) -> UserPublic:
    return UserPublic.model_validate(service.get_user(db, user_id))


@router.patch("/users/{userId}", operation_id="updateUser", **rbac(UserRole.ADMIN))
def update_user(
    user_id: UserId, body: UserUpdateRequest, db: DbDep, redis: RedisDep, settings: SettingsDep
) -> UserPublic:
    user = service.update_user(db, redis, settings, user_id, body.role, body.is_active)
    return UserPublic.model_validate(user)


@router.post(
    "/users/{userId}/password",
    operation_id="resetUserPassword",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    **rbac(UserRole.ADMIN),
)
def reset_user_password(
    user_id: UserId,
    body: UserPasswordResetRequest,
    db: DbDep,
    redis: RedisDep,
    settings: SettingsDep,
) -> Response:
    service.reset_password(db, redis, settings, user_id, body.password)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
