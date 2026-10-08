"""Notifications: уведомления, получатели, push-токены, доставка (C-10, C-11, C-13, C-14, A-03)."""

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, CreatedAtMixin, IdMixin, TimestampMixin
from app.models.enums import NotificationType, pg_enum


class Notification(IdMixin, CreatedAtMixin, Base):
    """target_vehicle_model_id — единственный источник таргетинга (NULL = все модели).

    Для type = 'firmware' обязательны релиз и модель; составной FK гарантирует, что релиз
    относится именно к этой модели.
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
        Index("ix_notification_created_at", "created_at"),
    )

    type: Mapped[NotificationType] = mapped_column(
        pg_enum(NotificationType, "notification_type"), nullable=False
    )
    firmware_release_id: Mapped[int | None] = mapped_column(BigInteger, index=True)
    target_vehicle_model_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("vehicle_model.id", ondelete="RESTRICT"), index=True
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
    __tablename__ = "push_token"

    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("app_user.id", ondelete="CASCADE"), nullable=False, index=True
    )
    token: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)


class NotificationDelivery(IdMixin, CreatedAtMixin, Base):
    """Технический журнал push-доставки для аналитики открываемости (Глава 16)."""

    __tablename__ = "notification_delivery"
    __table_args__ = (UniqueConstraint("notification_id", "push_token_id"),)

    notification_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("notification.id", ondelete="CASCADE"), nullable=False
    )
    push_token_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("push_token.id", ondelete="CASCADE"), nullable=False, index=True
    )
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    opened_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
