"""ORM-модели EV-ServiceDesk. Импорт всех модулей регистрирует таблицы в Base.metadata."""

from app.models.aggregates import (
    AggregateType,
    MaintenanceRecord,
    MaintenanceRegulation,
    VehicleAggregateStatus,
)
from app.models.auth import AppUser, PdConsent, RefreshToken
from app.models.base import Base
from app.models.knowledge import DecisionTreeNode, KnowledgeArticle
from app.models.notifications import (
    Notification,
    NotificationDelivery,
    NotificationRecipient,
    PushToken,
)
from app.models.tickets import Ticket, TicketAttachment, TicketMessage
from app.models.vehicles import FirmwareRelease, Vehicle, VehicleMileageCorrection, VehicleModel

__all__ = [
    "AggregateType",
    "AppUser",
    "Base",
    "DecisionTreeNode",
    "FirmwareRelease",
    "KnowledgeArticle",
    "MaintenanceRecord",
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
    "Vehicle",
    "VehicleAggregateStatus",
    "VehicleMileageCorrection",
    "VehicleModel",
]
