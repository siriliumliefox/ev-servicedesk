"""Схемы тега Analytics (A-05, A-06; Глава 16, ADR 0020)."""

from datetime import date, datetime

from pydantic import BaseModel

from app.api.pagination import PaginationMeta
from app.api.schemas.vehicles import VehicleModelOut
from app.models.enums import TicketCategory


class TicketResolutionStats(BaseModel):
    date_from: date
    date_to: date
    tickets_created: int
    tickets_resolved: int
    tickets_resolved_overdue: int
    avg_first_response_hours: float | None
    avg_resolution_hours: float | None
    median_resolution_hours: float | None
    computed_at: datetime


class TicketCategoryCount(BaseModel):
    category: TicketCategory
    count: int


class ProblemModelStats(BaseModel):
    vehicle_model: VehicleModelOut
    tickets_total: int
    vehicles_total: int
    by_category: list[TicketCategoryCount]


class ProblemModelStatsList(BaseModel):
    items: list[ProblemModelStats]
    meta: PaginationMeta
    computed_at: datetime


class MaintenanceConversionStats(BaseModel):
    date_from: date
    date_to: date
    tickets_total: int
    tickets_with_maintenance: int
    ticket_to_maintenance_rate: float | None
    notifications_recipients: int
    notifications_opened: int
    recipients_with_maintenance: int
    notification_to_maintenance_rate: float | None
    computed_at: datetime
