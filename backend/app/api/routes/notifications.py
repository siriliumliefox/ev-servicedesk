"""Notifications Service — тег Notifications контракта (Глава 15, ADR 0019).

Push-токены, центр уведомлений клиента, публикации администратора, релизы прошивок.
Отправку push выполняет worker (`app.workers.notifications`), а не запрос API.
"""

from typing import Annotated, Literal

from fastapi import APIRouter, Path, Query, Response, status

from app.api.deps import ALL_ROLES, CurrentUser, DbDep, OutboxDep, rbac
from app.api.pagination import PageDep, paginate, paginate_rows
from app.api.schemas.notifications import (
    FirmwareReleaseCreateRequest,
    FirmwareReleaseList,
    FirmwareReleaseOut,
    NotificationAudiencePreview,
    NotificationCreateRequest,
    NotificationDeliveryStats,
    NotificationList,
    NotificationListItem,
    NotificationOpenedRequest,
    NotificationOut,
    PublishedNotification,
    PublishedNotificationList,
    PushTokenRegisterRequest,
    VehicleFirmwareUpdateRequest,
)
from app.api.schemas.vehicles import VehicleOut
from app.core.audit import security_event
from app.core.db import BIGINT_MAX
from app.domain.notifications import service
from app.models.enums import STAFF_ROLES, NotificationType, UserRole

router = APIRouter(tags=["Notifications"])


# Диапазон BIGINT проверяет сервис (вне диапазона — 404, как у несуществующего id).
NotificationId = Annotated[int, Path(alias="notificationId")]
VehicleId = Annotated[int, Path(alias="vehicleId")]
ModelFilter = Annotated[int | None, Query(le=BIGINT_MAX)]
# Напоминания о ТО — не публикации: в фильтре контракта maintenance нет (422).
PublishedType = Literal["firmware", "news", "promo"]


@router.post(
    "/push-tokens",
    operation_id="registerPushToken",
    status_code=status.HTTP_201_CREATED,
    response_class=Response,
    **rbac(UserRole.CLIENT),
)
def register_push_token(body: PushTokenRegisterRequest, user: CurrentUser, db: DbDep) -> Response:
    service.register_token(db, user, body.token)
    return Response(status_code=status.HTTP_201_CREATED)


@router.delete(
    "/push-tokens/{token}",
    operation_id="deletePushToken",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    **rbac(UserRole.CLIENT),
)
def delete_push_token(token: Annotated[str, Path()], user: CurrentUser, db: DbDep) -> Response:
    # Без ограничений схемы: у операции нет 422 в контракте — недопустимый токен (длинный, с
    # управляющими символами) не существует, ответ — 404 (сервис; ZAP-1, глава 25).
    service.revoke_token(db, user, token)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/notifications", operation_id="listNotifications", **rbac(UserRole.CLIENT))
def list_notifications(user: CurrentUser, db: DbDep, page: PageDep) -> NotificationList:
    rows, meta = paginate_rows(db, service.feed_stmt(user), page)
    items = [
        NotificationListItem(**NotificationOut.model_validate(n).model_dump(), read_at=read_at)
        for n, read_at in rows
    ]
    return NotificationList(items=items, meta=meta)


@router.post(
    "/notifications",
    operation_id="createNotification",
    status_code=status.HTTP_201_CREATED,
    **rbac(UserRole.ADMIN),
)
def create_notification(
    body: NotificationCreateRequest, admin: CurrentUser, db: DbDep, outbox: OutboxDep
) -> NotificationOut:
    target = service.resolve_target(
        db, body.type, body.target_vehicle_model_id, body.firmware_release_id, for_publish=True
    )
    notification = service.publish(db, outbox, target, body.message)
    security_event(
        "notification.published", user_id=admin.id, target=f"notification:{notification.id}"
    )
    return NotificationOut.model_validate(notification)


@router.get(
    "/notifications/published",
    operation_id="listPublishedNotifications",
    **rbac(UserRole.ADMIN),
)
def list_published_notifications(
    db: DbDep,
    page: PageDep,
    type: PublishedType | None = None,  # noqa: A002 — имя параметра из контракта
    target_vehicle_model_id: ModelFilter = None,
) -> PublishedNotificationList:
    type_ = NotificationType(type) if type else None
    stmt = service.published_stmt(type_, target_vehicle_model_id)
    notifications, meta = paginate(db, stmt, page)
    stats = service.delivery_stats(db, [n.id for n in notifications])
    items = [
        PublishedNotification(
            **NotificationOut.model_validate(n).model_dump(),
            stats=NotificationDeliveryStats.model_validate(stats[n.id]),
        )
        for n in notifications
    ]
    return PublishedNotificationList(items=items, meta=meta)


@router.post(
    "/notifications/audience-preview",
    operation_id="previewNotificationAudience",
    **rbac(UserRole.ADMIN),
)
def preview_notification_audience(
    body: NotificationCreateRequest, db: DbDep
) -> NotificationAudiencePreview:
    target = service.resolve_target(
        db, body.type, body.target_vehicle_model_id, body.firmware_release_id
    )
    return NotificationAudiencePreview.model_validate(service.preview_audience(db, target))


@router.patch(
    "/notifications/{notificationId}/read",
    operation_id="markNotificationRead",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    **rbac(UserRole.CLIENT),
)
def mark_notification_read(
    notification_id: NotificationId, user: CurrentUser, db: DbDep
) -> Response:
    service.mark_read(db, user, notification_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/notifications/{notificationId}/opened",
    operation_id="markNotificationOpened",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    **rbac(UserRole.CLIENT),
)
def mark_notification_opened(
    notification_id: NotificationId,
    body: NotificationOpenedRequest,
    user: CurrentUser,
    db: DbDep,
) -> Response:
    service.mark_opened(db, user, notification_id, body.token)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/firmware-releases", operation_id="listFirmwareReleases", **rbac(*ALL_ROLES))
def list_firmware_releases(
    db: DbDep, page: PageDep, vehicle_model_id: ModelFilter = None
) -> FirmwareReleaseList:
    items, meta = paginate(db, service.list_firmware_stmt(vehicle_model_id), page)
    return FirmwareReleaseList(items=items, meta=meta)


@router.post(
    "/firmware-releases",
    operation_id="createFirmwareRelease",
    status_code=status.HTTP_201_CREATED,
    **rbac(UserRole.ADMIN),
)
def create_firmware_release(
    body: FirmwareReleaseCreateRequest, admin: CurrentUser, db: DbDep, outbox: OutboxDep
) -> FirmwareReleaseOut:
    release = service.create_firmware_release(
        db, outbox, body.vehicle_model_id, body.version, body.released_at
    )
    security_event("firmware.released", user_id=admin.id, target=f"firmware:{release.id}")
    return FirmwareReleaseOut.model_validate(release)


@router.patch(
    "/vehicles/{vehicleId}/firmware", operation_id="setVehicleFirmware", **rbac(*STAFF_ROLES)
)
def set_vehicle_firmware(
    vehicle_id: VehicleId, body: VehicleFirmwareUpdateRequest, user: CurrentUser, db: DbDep
) -> VehicleOut:
    vehicle = service.set_vehicle_firmware(db, user, vehicle_id, body.firmware_release_id)
    return VehicleOut.model_validate(vehicle)
