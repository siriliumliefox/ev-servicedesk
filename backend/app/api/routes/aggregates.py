"""Aggregates & Maintenance Service — тег Aggregates контракта (Глава 12, ADR 0016).

Справочник агрегатов, регламенты ТО, статусы «светофор» авто, замена агрегата, пороги.
"""

from typing import Annotated

from fastapi import APIRouter, Path, Query, Response, status

from app.api.deps import ALL_ROLES, CurrentUser, DbDep, rbac
from app.api.pagination import PageDep, paginate
from app.api.schemas.aggregates import (
    AggregateReplaceRequest,
    AggregateStatusList,
    AggregateStatusOut,
    AggregateStatusThresholdsOut,
    AggregateStatusThresholdsUpdateRequest,
    AggregateTypeCreateRequest,
    AggregateTypeList,
    AggregateTypeOut,
    MaintenanceRegulationCreateRequest,
    MaintenanceRegulationList,
    MaintenanceRegulationOut,
)
from app.domain.aggregates import service
from app.domain.vehicles.access import BIGINT_MAX
from app.models.enums import UserRole

router = APIRouter(tags=["Aggregates"])

STAFF = (UserRole.ENGINEER, UserRole.ADMIN)

# Диапазон BIGINT проверяют access и сервис (вне диапазона — 404, как у несуществующего id).
VehicleId = Annotated[int, Path(alias="vehicleId")]
RegulationId = Annotated[int, Path(alias="regulationId")]


@router.get("/aggregate-types", operation_id="listAggregateTypes", **rbac(*ALL_ROLES))
def list_aggregate_types(db: DbDep, page: PageDep) -> AggregateTypeList:
    items, meta = paginate(db, service.list_aggregate_types_stmt(), page)
    return AggregateTypeList(items=items, meta=meta)


@router.post(
    "/aggregate-types",
    operation_id="createAggregateType",
    status_code=status.HTTP_201_CREATED,
    **rbac(UserRole.ADMIN),
)
def create_aggregate_type(body: AggregateTypeCreateRequest, db: DbDep) -> AggregateTypeOut:
    return AggregateTypeOut.model_validate(service.create_aggregate_type(db, body.code, body.name))


@router.get("/maintenance-regulations", operation_id="listMaintenanceRegulations", **rbac(*STAFF))
def list_maintenance_regulations(
    db: DbDep,
    page: PageDep,
    vehicle_model_id: Annotated[int | None, Query(le=BIGINT_MAX)] = None,
    include_archived: bool = False,
) -> MaintenanceRegulationList:
    stmt = service.list_regulations_stmt(vehicle_model_id, include_archived)
    items, meta = paginate(db, stmt, page)
    return MaintenanceRegulationList(items=items, meta=meta)


@router.post(
    "/maintenance-regulations",
    operation_id="reviseMaintenanceRegulation",
    status_code=status.HTTP_201_CREATED,
    **rbac(UserRole.ADMIN),
)
def revise_maintenance_regulation(
    body: MaintenanceRegulationCreateRequest, db: DbDep
) -> MaintenanceRegulationOut:
    regulation = service.revise_regulation(
        db, body.vehicle_model_id, body.aggregate_type_code, body.interval_km, body.interval_months
    )
    return MaintenanceRegulationOut.model_validate(regulation)


@router.delete(
    "/maintenance-regulations/{regulationId}",
    operation_id="archiveMaintenanceRegulation",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    **rbac(UserRole.ADMIN),
)
def archive_maintenance_regulation(regulation_id: RegulationId, db: DbDep) -> Response:
    service.archive_regulation(db, regulation_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get(
    "/vehicles/{vehicleId}/aggregate-statuses",
    operation_id="listAggregateStatuses",
    **rbac(*ALL_ROLES),
)
def list_aggregate_statuses(
    vehicle_id: VehicleId, user: CurrentUser, db: DbDep, page: PageDep
) -> AggregateStatusList:
    vehicle, stmt = service.statuses_stmt(db, user, vehicle_id)
    regulations, meta = paginate(db, stmt, page)
    items = [
        AggregateStatusOut.model_validate(v) for v in service.statuses_for(db, vehicle, regulations)
    ]
    return AggregateStatusList(items=items, meta=meta)


@router.post(
    "/vehicles/{vehicleId}/aggregate-statuses/{aggregateTypeCode}/replace",
    operation_id="replaceAggregateStatus",
    **rbac(*STAFF),
)
def replace_aggregate_status(
    vehicle_id: VehicleId,
    aggregate_type_code: Annotated[str, Path(alias="aggregateTypeCode", max_length=50)],
    body: AggregateReplaceRequest,
    user: CurrentUser,
    db: DbDep,
) -> AggregateStatusOut:
    view = service.replace_aggregate(
        db,
        user,
        vehicle_id,
        aggregate_type_code,
        replaced_at=body.replaced_at,
        mileage_at_replacement=body.mileage_at_replacement,
        description=body.description,
    )
    return AggregateStatusOut.model_validate(view)


@router.get(
    "/aggregate-status-thresholds",
    operation_id="getAggregateStatusThresholds",
    **rbac(*STAFF),
)
def get_aggregate_status_thresholds(db: DbDep) -> AggregateStatusThresholdsOut:
    return AggregateStatusThresholdsOut.model_validate(service.get_thresholds(db))


@router.put(
    "/aggregate-status-thresholds",
    operation_id="updateAggregateStatusThresholds",
    **rbac(UserRole.ADMIN),
)
def update_aggregate_status_thresholds(
    body: AggregateStatusThresholdsUpdateRequest, user: CurrentUser, db: DbDep
) -> AggregateStatusThresholdsOut:
    thresholds = service.update_thresholds(
        db, user, body.yellow_from_percent, body.red_above_percent
    )
    return AggregateStatusThresholdsOut.model_validate(thresholds)
