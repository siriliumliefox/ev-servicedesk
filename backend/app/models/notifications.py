"""Notifications: уведомления, получатели, push-токены, доставка (C-10, C-11, C-13, C-14, A-03).

Исходящая очередь push — строки `notification_delivery` без `delivered_at`/`failed_at`;
push-токены отзываются мягко (`revoked_at`), журнал доставок сохраняется (ADR 0019).
"""

from datetime import date, datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, CreatedAtMixin, IdMixin, TimestampMixin
from app.models.enums import MaintenanceReminderKind, NotificationType, pg_enum

PUSH_TOKEN_MAX_LENGTH = 1024


class Notification(IdMixin, CreatedAtMixin, Base):
    """target_vehicle_model_id — единственный источник таргетинга (NULL = все модели).

    Для type = 'firmware' обязательны релиз и модель; составной FK гарантирует, что релиз
    относится именно к этой модели.
    """

    __tablename__ = "notification"
    __table_args__ = (
        CheckConstraint(
            "type <> 'firmware' OR firmware_release_id IS NOT NULL", name="firmware_has_release"
        ),
        CheckConstraint(
            "firmware_release_id IS NULL OR target_vehicle_model_id IS NOT NULL",
            name="firmware_requires_model",
        ),
        ForeignKeyConstraint(
            ["firmware_release_id", "target_vehicle_model_id"],
            ["firmware_release.id", "firmware_release.vehicle_model_id"],
            name="fk_notification_firmware_same_model",
            ondelete="RESTRICT",
        ),
        # Напоминание о ТО (ADR 0019 п. 6) — про конкретное авто и агрегат; остальные типы — нет.
        CheckConstraint(
            "(type = 'maintenance') = (vehicle_id IS NOT NULL) "
            "AND (vehicle_id IS NULL) = (aggregate_type_id IS NULL)",
            name="maintenance_target",
        ),
        Index("ix_notification_created_at", "created_at"),
        # Список рассылок администратора (published_stmt): без напоминаний о ТО (ADR 0028 п. 15).
        Index(
            "ix_notification_published",
            text("created_at DESC"),
            text("id DESC"),
            postgresql_where=text("type IN ('firmware', 'news', 'promo')"),
        ),
    )

    type: Mapped[NotificationType] = mapped_column(
        pg_enum(NotificationType, "notification_type"), nullable=False
    )
    firmware_release_id: Mapped[int | None] = mapped_column(BigInteger, index=True)
    target_vehicle_model_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("vehicle_model.id", ondelete="RESTRICT"), index=True
    )
    vehicle_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("vehicle.id", ondelete="RESTRICT"), index=True
    )
    aggregate_type_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("aggregate_type.id", ondelete="RESTRICT"), index=True
    )
    message: Mapped[str] = mapped_column(Text, nullable=False)


class NotificationRecipient(IdMixin, CreatedAtMixin, Base):
    """Лента и прочтение на уровне пользователя (C-13), независимо от push-токенов."""

    __tablename__ = "notification_recipient"
    __table_args__ = (
        UniqueConstraint("notification_id", "user_id"),
        Index("ix_notification_recipient_user_id_created_at", "user_id", "created_at"),
    )

    notification_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("notification.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("app_user.id", ondelete="CASCADE"), nullable=False
    )
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class PushToken(IdMixin, TimestampMixin, Base):
    """Токен устройства; уникален среди активных. Отзыв — `revoked_at` (ADR 0019 п. 8)."""

    __tablename__ = "push_token"
    __table_args__ = (
        Index(
            "uq_push_token_token_active",
            "token",
            unique=True,
            postgresql_where=text("revoked_at IS NULL"),
        ),
    )

    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("app_user.id", ondelete="CASCADE"), nullable=False, index=True
    )
    token: Mapped[str] = mapped_column(String(PUSH_TOKEN_MAX_LENGTH), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class NotificationDelivery(IdMixin, CreatedAtMixin, Base):
    """Технический журнал push-доставки для аналитики открываемости (Глава 16)."""

    __tablename__ = "notification_delivery"
    __table_args__ = (
        UniqueConstraint("notification_id", "push_token_id"),
        CheckConstraint("delivered_at IS NULL OR failed_at IS NULL", name="delivered_or_failed"),
        CheckConstraint("attempts >= 0", name="attempts_non_negative"),
        # Очередь отправки: ждущие строки в порядке срока попытки (ADR 0019 п. 2, 9).
        Index(
            "ix_notification_delivery_pending",
            "next_attempt_at",
            "id",
            postgresql_where=text("delivered_at IS NULL AND failed_at IS NULL"),
        ),
    )

    notification_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("notification.id", ondelete="CASCADE"), nullable=False
    )
    push_token_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("push_token.id", ondelete="CASCADE"), nullable=False, index=True
    )
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    opened_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    attempts: Mapped[int] = mapped_column(SmallInteger, server_default=text("0"), nullable=False)
    next_attempt_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    failed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_code: Mapped[str | None] = mapped_column(String(50))


class MaintenanceReminder(IdMixin, CreatedAtMixin, Base):
    """Учёт напоминаний о ТО: не больше одного каждого вида на цикл замены (ADR 0019 п. 6).

    Цикл — последняя замена агрегата (дата и пробег из `vehicle_aggregate_status`); неизвестные
    значения сравниваются как равные (NULLS NOT DISTINCT).
    """

    __tablename__ = "maintenance_reminder"
    __table_args__ = (
        UniqueConstraint(
            "vehicle_id",
            "aggregate_type_id",
            "kind",
            "cycle_replaced_at",
            "cycle_replaced_mileage",
            name="uq_maintenance_reminder_cycle",
            postgresql_nulls_not_distinct=True,
        ),
    )

    # RESTRICT, как у notification.vehicle_id: авто удаляется мягко; физическое удаление
    # (анонимизация, глава 25) удаляет напоминания явно.
    vehicle_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("vehicle.id", ondelete="RESTRICT"), nullable=False
    )
    aggregate_type_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("aggregate_type.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    kind: Mapped[MaintenanceReminderKind] = mapped_column(
        pg_enum(MaintenanceReminderKind, "maintenance_reminder_kind"), nullable=False
    )
    cycle_replaced_at: Mapped[date | None] = mapped_column(Date)
    cycle_replaced_mileage: Mapped[int | None] = mapped_column(Integer)
    notification_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("notification.id", ondelete="CASCADE"), nullable=False, index=True
    )
