"""Сценарии Notifications Service (Глава 15, ADR 0019).

Публикация — одна транзакция: уведомление, снимок аудитории (`notification_recipient`) и
исходящая очередь (`notification_delivery` на каждый активный токен получателя). После COMMIT
worker будится сигналом Redis (`Outbox.wake`); потерянный сигнал подхватит опрос очереди.
Аудитория и очередь заполняются `INSERT ... SELECT` — без выборки клиентов в память.
"""

from dataclasses import dataclass
from datetime import UTC, date, datetime

from sqlalchemy import (
    BigInteger,
    ColumnElement,
    Select,
    exists,
    func,
    insert,
    literal,
    or_,
    select,
    tuple_,
    update,
)
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, aliased

from app.core.db import constraint_name, get_by_id, is_db_id
from app.core.errors import ApiError
from app.domain.aggregates.service import today_in_business_tz
from app.domain.notifications.outbox import Outbox
from app.domain.vehicles import access
from app.domain.vehicles.service import VEHICLE_OUT
from app.models import (
    AppUser,
    FirmwareRelease,
    Notification,
    NotificationDelivery,
    NotificationRecipient,
    PdConsent,
    PushToken,
    Vehicle,
    VehicleModel,
)
from app.models.enums import NotificationType, UserRole

PUBLISHED_TYPES = (NotificationType.FIRMWARE, NotificationType.NEWS, NotificationType.PROMO)


def _field_error(field: str, code: str, message: str) -> ApiError:
    return ApiError(422, code, message, details={"fields": [{"loc": ["body", field]}]})


def _now() -> datetime:
    return datetime.now(UTC)


# ---------- Push-токены (ADR 0019 п. 8) ----------


def register_token(db: Session, user: AppUser, token: str) -> None:
    """POST /push-tokens: свой токен — обновить; чужой (сменили аккаунт) — перепривязать.

    Активная строка токена блокируется; в гонке двух регистраций одного токена вторая
    упирается в `uq_push_token_token_active` и повторяет попытку уже с найденной строкой.
    """
    for _ in range(2):
        current = db.scalars(
            select(PushToken)
            .where(PushToken.token == token, PushToken.revoked_at.is_(None))
            .with_for_update()
        ).one_or_none()
        if current is not None and current.user_id == user.id:
            current.updated_at = _now()  # отметка «устройство живо»; триггер выставит своё
            db.commit()
            return
        if current is not None:
            current.revoked_at = _now()
        db.add(PushToken(user_id=user.id, token=token))
        try:
            db.commit()
            return
        except IntegrityError as exc:
            db.rollback()
            if constraint_name(exc) != "uq_push_token_token_active":
                raise
    raise ApiError(409, "PUSH_TOKEN_CONFLICT", "Токен регистрируется одновременно — повторите")


def revoke_token(db: Session, user: AppUser, token: str) -> None:
    """DELETE /push-tokens/{token}: только свой активный токен, иначе 404."""
    revoked = db.execute(
        update(PushToken)
        .where(
            PushToken.token == token,
            PushToken.user_id == user.id,
            PushToken.revoked_at.is_(None),
        )
        .values(revoked_at=func.now())
    ).rowcount
    if not revoked:
        raise ApiError(404, "PUSH_TOKEN_NOT_FOUND", "Токен не найден")
    db.commit()


def revoke_all_tokens(db: Session, user_id: int) -> None:
    """Отзыв согласия ПД: все токены пользователя (без COMMIT — в транзакции вызывающего)."""
    db.execute(
        update(PushToken)
        .where(PushToken.user_id == user_id, PushToken.revoked_at.is_(None))
        .values(revoked_at=func.now())
    )


def active_tokens(db: Session, user_id: int) -> list[PushToken]:
    return list(
        db.scalars(
            select(PushToken)
            .where(PushToken.user_id == user_id, PushToken.revoked_at.is_(None))
            .order_by(PushToken.id)
        )
    )


# ---------- Аудитория (ADR 0019 п. 3, 4, 18) ----------


def eligible_client() -> list[ColumnElement[bool]]:
    """Активный клиент с действующим согласием ПД — единственный, кто получает уведомления."""
    consent = exists(
        select(PdConsent.id).where(
            PdConsent.user_id == AppUser.id, PdConsent.withdrawn_at.is_(None)
        )
    )
    return [
        AppUser.role == UserRole.CLIENT,
        AppUser.is_active.is_(True),
        AppUser.anonymized_at.is_(None),
        consent,
    ]


def _owners(model_id: int, firmware: FirmwareRelease | None) -> Select:
    """Владельцы неудалённых авто модели; для прошивки — с более ранней или неизвестной."""
    stmt = select(Vehicle.user_id).where(
        Vehicle.vehicle_model_id == model_id, Vehicle.deleted_at.is_(None)
    )
    if firmware is not None:
        current = aliased(FirmwareRelease)
        stmt = stmt.outerjoin(current, current.id == Vehicle.current_firmware_release_id).where(
            or_(
                current.id.is_(None),
                tuple_(current.released_at, current.id)
                < tuple_(literal(firmware.released_at), literal(firmware.id, BigInteger)),
            )
        )
    return stmt


def audience_stmt(model_id: int | None, firmware: FirmwareRelease | None) -> Select:
    """id клиентов аудитории: все клиенты (model_id = None) или владельцы авто модели."""
    stmt = select(AppUser.id).where(*eligible_client())
    if model_id is not None:
        stmt = stmt.where(AppUser.id.in_(_owners(model_id, firmware)))
    return stmt


@dataclass(frozen=True)
class Target:
    """Проверенная цель публикации."""

    type: NotificationType
    model: VehicleModel | None
    firmware: FirmwareRelease | None


def resolve_target(
    db: Session,
    type_: NotificationType,
    target_vehicle_model_id: int | None,
    firmware_release_id: int | None,
) -> Target:
    """Проверки createNotification и previewNotificationAudience (ADR 0019 п. 4, 6)."""
    if type_ is NotificationType.MAINTENANCE:
        raise _field_error(
            "type",
            "NOTIFICATION_TYPE_RESERVED",
            "Напоминания о ТО создаёт система, публиковать их нельзя",
        )
    model = None
    if target_vehicle_model_id is not None:
        model = db.get(VehicleModel, target_vehicle_model_id)
        if model is None:
            raise _field_error(
                "target_vehicle_model_id", "VEHICLE_MODEL_NOT_FOUND", "Модель не найдена"
            )
    if type_ is not NotificationType.FIRMWARE:
        if firmware_release_id is not None:
            raise _field_error(
                "firmware_release_id",
                "FIRMWARE_RELEASE_NOT_ALLOWED",
                "Релиз прошивки указывается только для уведомления о прошивке",
            )
        return Target(type_, model, None)
    if firmware_release_id is None:
        raise _field_error(
            "firmware_release_id", "FIRMWARE_RELEASE_REQUIRED", "Укажите релиз прошивки"
        )
    firmware = db.get(FirmwareRelease, firmware_release_id)
    if firmware is None:
        raise _field_error(
            "firmware_release_id", "FIRMWARE_RELEASE_NOT_FOUND", "Релиз прошивки не найден"
        )
    if model is not None and model.id != firmware.vehicle_model_id:
        raise _field_error(
            "firmware_release_id",
            "FIRMWARE_MODEL_MISMATCH",
            "Релиз относится к другой модели",
        )
    return Target(type_, db.get_one(VehicleModel, firmware.vehicle_model_id), firmware)


@dataclass(frozen=True)
class AudienceSize:
    recipients: int
    devices: int


def preview_audience(db: Session, target: Target) -> AudienceSize:
    """POST /notifications/audience-preview: ничего не пишет (ADR 0019 п. 12, U-45)."""
    users = audience_stmt(target.model.id if target.model else None, target.firmware).subquery()
    recipients = db.scalar(select(func.count()).select_from(users)) or 0
    devices = (
        db.scalar(
            select(func.count(PushToken.id)).where(
                PushToken.user_id.in_(select(users.c.id)), PushToken.revoked_at.is_(None)
            )
        )
        or 0
    )
    return AudienceSize(recipients, devices)


# ---------- Публикация ----------


def enqueue(db: Session, notification: Notification, users: Select) -> None:
    """Снимок аудитории и строки очереди на активные токены (без COMMIT)."""
    nid = literal(notification.id, BigInteger)
    db.execute(
        insert(NotificationRecipient).from_select(
            ["notification_id", "user_id"], select(nid, users.subquery().c.id)
        )
    )
    recipients = select(NotificationRecipient.user_id).where(
        NotificationRecipient.notification_id == notification.id
    )
    db.execute(
        insert(NotificationDelivery).from_select(
            ["notification_id", "push_token_id"],
            select(nid, PushToken.id).where(
                PushToken.user_id.in_(recipients), PushToken.revoked_at.is_(None)
            ),
        )
    )


def _publish(db: Session, outbox: Outbox, target: Target, message: str) -> Notification:
    notification = Notification(
        type=target.type,
        target_vehicle_model_id=target.model.id if target.model else None,
        firmware_release_id=target.firmware.id if target.firmware else None,
        message=message,
    )
    db.add(notification)
    db.flush()
    enqueue(db, notification, audience_stmt(notification.target_vehicle_model_id, target.firmware))
    db.commit()
    outbox.wake()
    return notification


def publish(db: Session, outbox: Outbox, target: Target, message: str) -> Notification:
    """POST /notifications (admin): публикация новости, акции или прошивки."""
    return _publish(db, outbox, target, message)


# ---------- Лента клиента ----------


@dataclass(frozen=True)
class FeedItem:
    notification: Notification
    read_at: datetime | None


def feed_stmt(user: AppUser) -> Select:
    return (
        select(Notification, NotificationRecipient.read_at)
        .join(NotificationRecipient, NotificationRecipient.notification_id == Notification.id)
        .where(NotificationRecipient.user_id == user.id)
        .order_by(NotificationRecipient.created_at.desc(), Notification.id.desc())
    )


def _recipient(db: Session, user: AppUser, notification_id: int) -> NotificationRecipient:
    not_found = ApiError(404, "NOTIFICATION_NOT_FOUND", "Уведомление не найдено")
    if not is_db_id(notification_id):
        raise not_found
    row = db.scalars(
        select(NotificationRecipient)
        .where(
            NotificationRecipient.notification_id == notification_id,
            NotificationRecipient.user_id == user.id,
        )
        .with_for_update()
    ).one_or_none()
    if row is None:
        raise not_found
    return row


def mark_read(db: Session, user: AppUser, notification_id: int) -> None:
    """PATCH /notifications/{id}/read: первое прочтение сохраняется."""
    row = _recipient(db, user, notification_id)
    if row.read_at is None:
        row.read_at = _now()
    db.commit()


def mark_opened(db: Session, user: AppUser, notification_id: int, token: str) -> None:
    """POST /notifications/{id}/opened: opened_at доставки на это устройство и read_at."""
    row = _recipient(db, user, notification_id)
    now = _now()
    if row.read_at is None:
        row.read_at = now
    db.execute(
        update(NotificationDelivery)
        .where(
            NotificationDelivery.notification_id == notification_id,
            NotificationDelivery.opened_at.is_(None),
            NotificationDelivery.push_token_id.in_(
                select(PushToken.id).where(PushToken.user_id == user.id, PushToken.token == token)
            ),
        )
        .values(opened_at=now)
    )
    db.commit()


# ---------- Лента публикаций (admin) ----------


@dataclass(frozen=True)
class DeliveryStats:
    recipients: int
    delivered: int
    failed: int
    opened: int
    read: int


def published_stmt(type_: NotificationType | None, target_vehicle_model_id: int | None) -> Select:
    stmt = (
        select(Notification)
        .where(Notification.type.in_(PUBLISHED_TYPES))
        .order_by(Notification.created_at.desc(), Notification.id.desc())
    )
    if type_ is not None:
        stmt = stmt.where(Notification.type == type_)
    if target_vehicle_model_id is not None:
        stmt = stmt.where(Notification.target_vehicle_model_id == target_vehicle_model_id)
    return stmt


def delivery_stats(db: Session, ids: list[int]) -> dict[int, DeliveryStats]:
    """Счётчики страницы публикаций — два агрегирующих запроса на всю страницу."""
    if not ids:
        return {}
    recipients = {
        nid: (total, read)
        for nid, total, read in db.execute(
            select(
                NotificationRecipient.notification_id,
                func.count(),
                func.count(NotificationRecipient.read_at),
            )
            .where(NotificationRecipient.notification_id.in_(ids))
            .group_by(NotificationRecipient.notification_id)
        )
    }
    deliveries = {
        nid: (delivered, failed, opened)
        for nid, delivered, failed, opened in db.execute(
            select(
                NotificationDelivery.notification_id,
                func.count(NotificationDelivery.delivered_at),
                func.count(NotificationDelivery.failed_at),
                func.count(NotificationDelivery.opened_at),
            )
            .where(NotificationDelivery.notification_id.in_(ids))
            .group_by(NotificationDelivery.notification_id)
        )
    }
    stats = {}
    for nid in ids:
        total, read = recipients.get(nid, (0, 0))
        delivered, failed, opened = deliveries.get(nid, (0, 0, 0))
        stats[nid] = DeliveryStats(total, delivered, failed, opened, read)
    return stats


# ---------- Прошивки (ADR 0019 п. 4) ----------


def list_firmware_stmt(vehicle_model_id: int | None) -> Select:
    stmt = select(FirmwareRelease).order_by(
        FirmwareRelease.released_at.desc(), FirmwareRelease.id.desc()
    )
    if vehicle_model_id is not None:
        stmt = stmt.where(FirmwareRelease.vehicle_model_id == vehicle_model_id)
    return stmt


def firmware_message(model: VehicleModel, version: str) -> str:
    return f"Для {model.brand} {model.model} доступна прошивка {version}"


def create_firmware_release(
    db: Session,
    outbox: Outbox,
    vehicle_model_id: int,
    version: str,
    released_at: date,
    today: date | None = None,
) -> FirmwareRelease:
    """POST /firmware-releases (admin): релиз и уведомление владельцам — одной транзакцией."""
    today = today or today_in_business_tz()
    model = db.get(VehicleModel, vehicle_model_id) if is_db_id(vehicle_model_id) else None
    if model is None:
        raise _field_error("vehicle_model_id", "VEHICLE_MODEL_NOT_FOUND", "Модель не найдена")
    if released_at > today:
        raise _field_error("released_at", "RELEASED_AT_IN_FUTURE", "Дата выпуска в будущем")
    release = FirmwareRelease(vehicle_model_id=model.id, version=version, released_at=released_at)
    db.add(release)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        if constraint_name(exc) != "uq_firmware_release_vehicle_model_id_version":
            raise
        raise _field_error(
            "version", "FIRMWARE_VERSION_EXISTS", "Такая версия прошивки модели уже есть"
        ) from exc
    _publish(
        db,
        outbox,
        Target(NotificationType.FIRMWARE, model, release),
        firmware_message(model, version),
    )
    return release


def set_vehicle_firmware(
    db: Session, user: AppUser, vehicle_id: int, firmware_release_id: int
) -> Vehicle:
    """PATCH /vehicles/{id}/firmware (engineer/admin): доступ — как у записи работ (ADR 0014).

    Уведомлений не создаёт; ответ — авто с моделью и версией прошивки после COMMIT.
    """
    vehicle = access.for_change(db, user, vehicle_id).vehicle
    release = get_by_id(db, FirmwareRelease, firmware_release_id)
    if release is None or release.vehicle_model_id != vehicle.vehicle_model_id:
        raise _field_error(
            "firmware_release_id",
            "FIRMWARE_RELEASE_NOT_FOUND",
            "Релиз прошивки этой модели не найден",
        )
    vehicle.current_firmware_release_id = release.id
    db.commit()
    return db.get_one(Vehicle, vehicle.id, options=VEHICLE_OUT, populate_existing=True)
