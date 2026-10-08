"""Стабильные наборы значений — нативные PostgreSQL ENUM (ADR 0003).

Значения совпадают с enum в docs/openapi.yaml; расширяемые справочники
(aggregate_type) — отдельные таблицы, а не ENUM.
"""

import enum

from sqlalchemy import Enum


class UserRole(enum.StrEnum):
    CLIENT = "client"
    ENGINEER = "engineer"
    ADMIN = "admin"


class TicketCategory(enum.StrEnum):
    NAVIGATION = "navigation"
    AUDIO = "audio"
    SIM = "sim"
    APP_CRASH = "app_crash"
    MAINTENANCE = "maintenance"


class TicketStatus(enum.StrEnum):
    NEW = "new"
    IN_PROGRESS = "in_progress"
    WAITING_VENDOR = "waiting_vendor"
    RESOLVED = "resolved"


class AttachmentType(enum.StrEnum):
    PHOTO = "photo"
    VIDEO = "video"


class KbArticleType(enum.StrEnum):
    GUIDE = "guide"
    TROUBLESHOOTING = "troubleshooting"


class NotificationType(enum.StrEnum):
    FIRMWARE = "firmware"
    MAINTENANCE = "maintenance"
    NEWS = "news"
    PROMO = "promo"


def pg_enum(enum_cls: type[enum.StrEnum], name: str) -> Enum:
    """ENUM, хранящий value ("in_progress"), а не имя члена ("IN_PROGRESS")."""
    return Enum(
        enum_cls,
        name=name,
        values_callable=lambda members: [m.value for m in members],
        validate_strings=True,
    )


PG_ENUMS: dict[str, type[enum.StrEnum]] = {
    "user_role": UserRole,
    "ticket_category": TicketCategory,
    "ticket_status": TicketStatus,
    "attachment_type": AttachmentType,
    "kb_article_type": KbArticleType,
    "notification_type": NotificationType,
}
