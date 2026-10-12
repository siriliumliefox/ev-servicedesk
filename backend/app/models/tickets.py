"""Tickets: тикеты, чат, вложения, нормативы SLA (C-08, C-09, E-01, E-02, E-04, A-05, N-09)."""

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    and_,
    func,
    select,
    text,
)
from sqlalchemy.orm import Mapped, column_property, mapped_column, relationship

from app.models.auth import AppUser
from app.models.base import Base, CreatedAtMixin, IdMixin, TimestampMixin
from app.models.enums import AttachmentType, TicketCategory, TicketStatus, pg_enum
from app.models.vehicles import FirmwareRelease, Vehicle, VehicleModel

SUMMARY_LENGTH = 140  # Ticket.summary контракта (1.4.0, ADR 0017 п. 13)


class Ticket(IdMixin, TimestampMixin, Base):
    """Владелец тикета = vehicle.user_id (неизменяем, ADR 0003) — без дублирующего client_id (3НФ).

    firmware_release_id — снимок прошивки на момент создания (N-09): прошивка авто
    меняется со временем, поэтому это не транзитивная зависимость. Модель берётся из vehicle.
    Claim атомарен: UPDATE ... WHERE assigned_engineer_id IS NULL RETURNING id.
    """

    __tablename__ = "ticket"
    __table_args__ = (
        CheckConstraint(
            "(status = 'resolved') = (resolved_at IS NOT NULL)", name="resolved_at_consistent"
        ),
        CheckConstraint("btrim(description) <> ''", name="description_not_blank"),
        Index("ix_ticket_status_sla_due_at", "status", "sla_due_at"),
    )

    vehicle_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("vehicle.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    category: Mapped[TicketCategory] = mapped_column(
        pg_enum(TicketCategory, "ticket_category"), nullable=False
    )
    status: Mapped[TicketStatus] = mapped_column(
        pg_enum(TicketStatus, "ticket_status"), server_default=text("'new'"), nullable=False
    )
    description: Mapped[str] = mapped_column(Text, nullable=False)
    assigned_engineer_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("app_user.id", ondelete="RESTRICT"), index=True
    )
    sla_due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    firmware_release_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("firmware_release.id", ondelete="RESTRICT"), index=True
    )
    source_article_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("knowledge_article.id", ondelete="SET NULL"), index=True
    )
    source_node_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("decision_tree_node.id", ondelete="SET NULL"), index=True
    )
    first_response_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # Связи только явной загрузкой (selectinload), ленивая подгрузка — ошибка (ADR 0015).
    vehicle: Mapped[Vehicle] = relationship(lazy="raise")
    # Вложения самого тикета; вложения сообщений — TicketMessage.attachments.
    attachments: Mapped[list["TicketAttachment"]] = relationship(
        primaryjoin="and_(Ticket.id == TicketAttachment.ticket_id, "
        "TicketAttachment.ticket_message_id.is_(None))",
        order_by="TicketAttachment.id",
        viewonly=True,
        lazy="raise",
    )
    # Просрочка вычисляется при чтении (ADR 0017 п. 3): поле ответа и фильтр `overdue` —
    # одно выражение SQL. now() — время начала читающей транзакции: одно для всей выборки.
    is_overdue: Mapped[bool] = column_property(
        and_(func.now() > sla_due_at, status != TicketStatus.RESOLVED)
    )
    # Снимок прошивки на момент создания (N-09) — версия подзапросом, как у Vehicle.
    firmware_version_at_creation: Mapped[str | None] = column_property(
        select(FirmwareRelease.version)
        .where(FirmwareRelease.id == firmware_release_id)
        .correlate_except(FirmwareRelease)
        .scalar_subquery()
    )

    @property
    def vehicle_model(self) -> VehicleModel:
        return self.vehicle.vehicle_model

    @property
    def summary(self) -> str:
        """Начало описания для карточки канбана и списка клиента — без многоточия."""
        return self.description[:SUMMARY_LENGTH]


class TicketMessage(IdMixin, CreatedAtMixin, Base):
    __tablename__ = "ticket_message"
    __table_args__ = (
        CheckConstraint("btrim(body) <> ''", name="body_not_blank"),
        # Цель составного FK из ticket_attachment (вложение и сообщение — одного тикета).
        UniqueConstraint("id", "ticket_id"),
        Index("ix_ticket_message_ticket_id_created_at", "ticket_id", "created_at"),
    )

    ticket_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("ticket.id", ondelete="RESTRICT"), nullable=False
    )
    author_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("app_user.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    body: Mapped[str] = mapped_column(Text, nullable=False)

    author: Mapped[AppUser] = relationship(lazy="raise")
    attachments: Mapped[list["TicketAttachment"]] = relationship(
        primaryjoin="TicketMessage.id == foreign(TicketAttachment.ticket_message_id)",
        order_by="TicketAttachment.id",
        viewonly=True,
        lazy="raise",
    )


class TicketAttachment(IdMixin, CreatedAtMixin, Base):
    """Хранится ключ объекта S3, а не URL (ADR 0004); URL выдаётся presigned при чтении.

    upload_name — имя исходной загрузки ({uuid}{расширение}, ADR 0017 п. 10): UNIQUE —
    одна загрузка становится не более чем одним вложением. object_key уникален для каждой
    попытки привязки.
    """

    __tablename__ = "ticket_attachment"
    __table_args__ = (
        CheckConstraint("size_bytes > 0", name="size_positive"),
        CheckConstraint(
            "(file_type = 'photo' AND mime_type LIKE 'image/%') "
            "OR (file_type = 'video' AND mime_type LIKE 'video/%')",
            name="mime_matches_type",
        ),
        ForeignKeyConstraint(
            ["ticket_message_id", "ticket_id"],
            ["ticket_message.id", "ticket_message.ticket_id"],
            name="fk_ticket_attachment_message_same_ticket",
            ondelete="RESTRICT",
        ),
    )

    ticket_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("ticket.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    # NULL = вложение создано вместе с тикетом.
    ticket_message_id: Mapped[int | None] = mapped_column(BigInteger, index=True)
    object_key: Mapped[str] = mapped_column(String(500), unique=True, nullable=False)
    upload_name: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    file_type: Mapped[AttachmentType] = mapped_column(
        pg_enum(AttachmentType, "attachment_type"), nullable=False
    )
    mime_type: Mapped[str] = mapped_column(String(100), nullable=False)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    uploaded_by_user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("app_user.id", ondelete="RESTRICT"), nullable=False, index=True
    )


class TicketSlaPolicy(TimestampMixin, Base):
    """Норматив SLA — срок решения тикета по категории (ADR 0017 п. 1–2); seed — миграция 0008.

    sla_due_at = created_at + resolution_minutes, вычисляется один раз при создании тикета:
    изменение норматива на созданные тикеты не влияет. API нет — нормативы меняет миграция.
    """

    __tablename__ = "ticket_sla_policy"
    __table_args__ = (
        CheckConstraint("resolution_minutes > 0", name="resolution_minutes_positive"),
    )

    category: Mapped[TicketCategory] = mapped_column(
        pg_enum(TicketCategory, "ticket_category"), primary_key=True, sort_order=-100
    )
    resolution_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
