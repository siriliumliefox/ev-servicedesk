"""Vehicle: модели, автомобили клиентов, релизы прошивок (C-02, C-03, C-12, A-03)."""

from datetime import date, datetime

from sqlalchemy import (
    CHAR,
    BigInteger,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, CreatedAtMixin, IdMixin, TimestampMixin


class VehicleModel(IdMixin, TimestampMixin, Base):
    __tablename__ = "vehicle_model"
    __table_args__ = (UniqueConstraint("brand", "model", "trim"),)

    brand: Mapped[str] = mapped_column(String(100), nullable=False)
    model: Mapped[str] = mapped_column(String(100), nullable=False)
    # '' = без комплектации: NULL сломал бы UNIQUE (NULL ≠ NULL). API отдаёт '' как null.
    trim: Mapped[str] = mapped_column(String(100), server_default=text("''"), nullable=False)


class FirmwareRelease(IdMixin, CreatedAtMixin, Base):
    __tablename__ = "firmware_release"
    __table_args__ = (
        UniqueConstraint("vehicle_model_id", "version"),
        # Цель составных FK "прошивка той же модели" (vehicle, knowledge_article, notification).
        UniqueConstraint("id", "vehicle_model_id"),
    )

    vehicle_model_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("vehicle_model.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    version: Mapped[str] = mapped_column(String(50), nullable=False)
    released_at: Mapped[date] = mapped_column(Date, nullable=False)


class Vehicle(IdMixin, TimestampMixin, Base):
    """VIN, владелец и модель неизменяемы (триггер vehicle_guard); пробег не уменьшается.

    Смена владельца = soft-delete старой записи и новая запись с тем же VIN (ADR 0003):
    история ТО и тикеты привязаны к vehicle.id и не видны новому владельцу.
    """

    __tablename__ = "vehicle"
    __table_args__ = (
        CheckConstraint("vin ~ '^[A-HJ-NPR-Z0-9]{17}$'", name="vin_format"),
        CheckConstraint("mileage >= 0", name="mileage_non_negative"),
        # Один активный автомобиль на VIN; soft-delete не блокирует повторное добавление.
        Index(
            "uq_vehicle_vin_active",
            "vin",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
        ),
        ForeignKeyConstraint(
            ["current_firmware_release_id", "vehicle_model_id"],
            ["firmware_release.id", "firmware_release.vehicle_model_id"],
            name="fk_vehicle_firmware_same_model",
            ondelete="RESTRICT",
        ),
    )

    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("app_user.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    vehicle_model_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("vehicle_model.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    vin: Mapped[str] = mapped_column(CHAR(17), nullable=False)
    mileage: Mapped[int] = mapped_column(Integer, server_default=text("0"), nullable=False)
    current_firmware_release_id: Mapped[int | None] = mapped_column(BigInteger, index=True)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
