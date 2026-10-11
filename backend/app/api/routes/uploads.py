"""Uploads — `POST /uploads/presign` контракта (тег Uploads, Глава 13, ADR 0017 п. 10)."""

from fastapi import APIRouter

from app.api.deps import CurrentUser, RedisDep, SettingsDep, StorageDep, rbac
from app.api.schemas.uploads import PresignRequest, PresignResponse
from app.domain.tickets import attachments
from app.models.enums import UserRole

router = APIRouter(tags=["Uploads"])


@router.post(
    "/uploads/presign",
    operation_id="createPresignedUpload",
    **rbac(UserRole.CLIENT, UserRole.ENGINEER),
)
def create_presigned_upload(
    body: PresignRequest,
    user: CurrentUser,
    redis: RedisDep,
    settings: SettingsDep,
    storage: StorageDep,
) -> PresignResponse:
    upload = attachments.presign_upload(
        redis, settings, storage, user, body.file_name, body.file_type
    )
    return PresignResponse.model_validate(upload)
