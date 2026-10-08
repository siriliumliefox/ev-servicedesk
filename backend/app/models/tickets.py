"""Tickets: тикеты, чат, вложения (C-08, C-09, E-01, E-02, E-04, A-05, N-09)."""

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
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, CreatedAtMixin, IdMixin, TimestampMixin
from app.models.enums import AttachmentType, TicketCategory, TicketStatus, pg_enum


class Ticket(IdMixin, TimestampMixin, Base):
    """Владелец тикета = vehicle.user_id (неизменяем, ADR 0003) — без дублирующего client_id (3НФ).

    firmware_release_id — снимок прошивки на момент создания (N-09): прошивка авто
    меняется со временем, поэтому это не транзитивная зависимость. Модель берётся из vehicle.
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


class TicketAttachment(IdMixin, CreatedAtMixin, Base):
    """Хранится ключ объекта S3, а не URL (ADR 0004); URL выдаётся presigned при чтении."""

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
    file_type: Mapped[AttachmentType] = mapped_column(
        pg_enum(AttachmentType, "attachment_type"), nullable=False
    )
    mime_type: Mapped[str] = mapped_column(String(100), nullable=False)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    uploaded_by_user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("app_user.id", ondelete="RESTRICT"), nullable=False, index=True
    )
