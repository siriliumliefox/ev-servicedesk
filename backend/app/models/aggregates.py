"""Aggregates & Maintenance: справочник, регламенты, статусы, история ТО.

C-03, C-04, C-05, E-05, A-01, A-06, A-07.
"""

from datetime import date

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Date,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, CreatedAtMixin, IdMixin, TimestampMixin


class AggregateType(IdMixin, TimestampMixin, Base):
    """Расширяемый справочник (A-07); seed — миграция 0002."""

    __tablename__ = "aggregate_type"
    __table_args__ = (CheckConstraint("code ~ '^[a-z][a-z0-9_]{1,49}$'", name="code_format"),)

    code: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)


class MaintenanceRegulation(IdMixin, TimestampMixin, Base):
    """Регламент не редактируется: старая версия архивируется, создаётся новая."""

    __tablename__ = "maintenance_regulation"
    __table_args__ = (
        CheckConstraint(
            "interval_km IS NOT NULL OR interval_months IS NOT NULL", name="interval_present"
        ),
        CheckConstraint("interval_km IS NULL OR interval_km > 0", name="interval_km_positive"),
        CheckConstraint(
            "interval_months IS NULL OR interval_months > 0", name="interval_months_positive"
        ),
        Index(
            "uq_maintenance_regulation_active",
            "vehicle_model_id",
            "aggregate_type_id",
            unique=True,
            postgresql_where=text("is_archived = false"),
        ),
    )

    vehicle_model_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("vehicle_model.id", ondelete="RESTRICT"), nullable=False
    )
    aggregate_type_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("aggregate_type.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    interval_km: Mapped[int | None] = mapped_column(Integer)
    interval_months: Mapped[int | None] = mapped_column(Integer)
    is_archived: Mapped[bool] = mapped_column(server_default=text("false"), nullable=False)


class VehicleAggregateStatus(IdMixin, TimestampMixin, Base):
    """Кэш последней замены для «светофора»: ровно одна запись на (авто, агрегат)."""

    __tablename__ = "vehicle_aggregate_status"
    __table_args__ = (
        UniqueConstraint("vehicle_id", "aggregate_type_id"),
        CheckConstraint(
            "last_replaced_mileage IS NULL OR last_replaced_mileage >= 0",
            name="last_replaced_mileage_non_negative",
        ),
    )

    vehicle_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("vehicle.id", ondelete="CASCADE"), nullable=False
    )
    aggregate_type_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("aggregate_type.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    last_replaced_at: Mapped[date | None] = mapped_column(Date)
    last_replaced_mileage: Mapped[int | None] = mapped_column(Integer)


class MaintenanceRecord(IdMixin, CreatedAtMixin, Base):
    """История ТО (append-only). ticket_id — связь «обращение → ТО» для A-06."""

    __tablename__ = "maintenance_record"
    __table_args__ = (
        CheckConstraint("mileage_at_service >= 0", name="mileage_at_service_non_negative"),
        CheckConstraint(
            "aggregate_type_id IS NOT NULL OR description IS NOT NULL", name="subject_present"
        ),
    )

    vehicle_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("vehicle.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    aggregate_type_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("aggregate_type.id", ondelete="RESTRICT"), index=True
    )
    performed_by_user_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("app_user.id", ondelete="RESTRICT"), index=True
    )
    ticket_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("ticket.id", ondelete="SET NULL"), index=True
    )
    performed_at: Mapped[date] = mapped_column(Date, nullable=False)
    mileage_at_service: Mapped[int] = mapped_column(Integer, nullable=False)
    description: Mapped[str | None] = mapped_column(String(255))
