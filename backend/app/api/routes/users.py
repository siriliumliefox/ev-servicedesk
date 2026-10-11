"""Users — профиль текущего пользователя (`/me`). Список и управление — Глава 22."""

from fastapi import APIRouter

from app.api.deps import ALL_ROLES, CurrentUser, rbac
from app.api.schemas.auth import UserPublic

router = APIRouter(tags=["Users"])


@router.get("/me", operation_id="getCurrentUser", **rbac(*ALL_ROLES))
def get_current_user_profile(user: CurrentUser) -> UserPublic:
    return UserPublic.model_validate(user)
