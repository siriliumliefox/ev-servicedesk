"""ORM-модели EV-ServiceDesk. Импорт всех модулей регистрирует таблицы в Base.metadata."""

from app.models.aggregates import (
    AggregateStatusThresholds,
    AggregateType,
    MaintenanceRecord,
    MaintenanceRegulation,
    VehicleAggregateStatus,
)
from app.models.analytics import AnalyticsRefresh
from app.models.auth import AppUser, PdConsent, RefreshToken
from app.models.base import Base
from app.models.knowledge import DecisionTreeNode, KnowledgeArticle, KnowledgeArticleRevision
from app.models.notifications import (
    MaintenanceReminder,
    Notification,
    NotificationDelivery,
    NotificationRecipient,
    PushToken,
)
from app.models.tickets import Ticket, TicketAttachment, TicketMessage, TicketSlaPolicy
from app.models.vehicles import FirmwareRelease, Vehicle, VehicleMileageCorrection, VehicleModel

__all__ = [
    "AggregateStatusThresholds",
    "AnalyticsRefresh",
    "AggregateType",
    "AppUser",
    "Base",
    "DecisionTreeNode",
    "FirmwareRelease",
    "KnowledgeArticle",
    "KnowledgeArticleRevision",
    "MaintenanceRecord",
    "MaintenanceReminder",
    "MaintenanceRegulation",
    "Notification",
    "NotificationDelivery",
    "NotificationRecipient",
    "PdConsent",
    "PushToken",
    "RefreshToken",
    "Ticket",
    "TicketAttachment",
    "TicketMessage",
    "TicketSlaPolicy",
    "Vehicle",
    "VehicleAggregateStatus",
    "VehicleMileageCorrection",
    "VehicleModel",
]
