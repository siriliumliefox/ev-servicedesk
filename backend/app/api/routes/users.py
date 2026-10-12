"""Users — профиль (`/me`) и управление пользователями (Глава 17, ADR 0021 п. 3)."""

from typing import Annotated

from fastapi import APIRouter, Path, Query, status

from app.api.deps import ALL_ROLES, CurrentUser, DbDep, rbac
from app.api.pagination import PageDep, paginate
from app.api.schemas.auth import (
    StaffUserCreateRequest,
    UserList,
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
def update_user(user_id: UserId, body: UserUpdateRequest, db: DbDep) -> UserPublic:
    return UserPublic.model_validate(service.update_user(db, user_id, body.role, body.is_active))
