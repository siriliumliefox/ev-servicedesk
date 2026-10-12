"""Analytics Service — тег Analytics контракта (Глава 16, ADR 0020).

Показатели дашборда администратора считаются по витрине фактов, которую обновляет
`analytics-worker`; свежесть — `computed_at`.
"""

from datetime import date
from typing import Annotated

from fastapi import APIRouter, Query

from app.api.deps import DbDep, rbac
from app.api.pagination import PageDep, paginate_rows
from app.api.schemas.analytics import (
    MaintenanceConversionStats,
    ProblemModelStats,
    ProblemModelStatsList,
    TicketResolutionStats,
)
from app.core.db import BIGINT_MAX
from app.domain.analytics import service
from app.domain.analytics.service import Period
from app.models.enums import TicketCategory, UserRole

router = APIRouter(tags=["Analytics"])

DateFrom = Annotated[date, Query()]
DateTo = Annotated[date, Query()]
ModelFilter = Annotated[int | None, Query(le=BIGINT_MAX)]


@router.get(
    "/analytics/ticket-resolution",
    operation_id="getTicketResolutionStats",
    **rbac(UserRole.ADMIN),
)
def get_ticket_resolution_stats(
    db: DbDep,
    date_from: DateFrom,
    date_to: DateTo,
    vehicle_model_id: ModelFilter = None,
    category: TicketCategory | None = None,
) -> TicketResolutionStats:
    stats = service.ticket_resolution(db, Period(date_from, date_to), vehicle_model_id, category)
    return TicketResolutionStats.model_validate(stats)


@router.get(
    "/analytics/problem-models",
    operation_id="listProblemModels",
    **rbac(UserRole.ADMIN),
)
def list_problem_models(
    db: DbDep, page: PageDep, date_from: DateFrom, date_to: DateTo
) -> ProblemModelStatsList:
    period = Period(date_from, date_to)
    fresh = service.problem_models_computed_at(db)  # до данных — см. service.computed_at
    rows, meta = paginate_rows(db, service.problem_models_stmt(period), page)
    items = [
        ProblemModelStats.model_validate(service.problem_model_item(row), from_attributes=True)
        for row in rows
    ]
    return ProblemModelStatsList(items=items, meta=meta, computed_at=fresh)


@router.get(
    "/analytics/maintenance-conversion",
    operation_id="getMaintenanceConversionStats",
    **rbac(UserRole.ADMIN),
)
def get_maintenance_conversion_stats(
    db: DbDep, date_from: DateFrom, date_to: DateTo, vehicle_model_id: ModelFilter = None
) -> MaintenanceConversionStats:
    stats = service.maintenance_conversion(db, Period(date_from, date_to), vehicle_model_id)
    return MaintenanceConversionStats.model_validate(stats)
