"""Vehicle Service — пути `/vehicles*` и `/vehicle-models` контракта (тег Vehicle, Глава 11).

Прошивка авто (`/vehicles/{id}/firmware`) — тег Notifications; статусы агрегатов — Глава 12.
"""

from typing import Annotated

from fastapi import APIRouter, Path, Query, Response, status

from app.api.deps import (
    ALL_ROLES,
    CurrentUser,
    DbDep,
    RedisDep,
    SettingsDep,
    VinDecoderDep,
    rbac,
)
from app.api.pagination import PageDep, paginate
from app.api.schemas.vehicles import (
    MaintenanceRecordCreateRequest,
    MaintenanceRecordList,
    MaintenanceRecordOut,
    MileageCorrectionRequest,
    MileageUpdateRequest,
    VehicleCreateRequest,
    VehicleList,
    VehicleModelList,
    VehicleOut,
)
from app.domain.vehicles import service
from app.models.enums import STAFF_ROLES, UserRole

router = APIRouter(tags=["Vehicle"])


# Диапазон BIGINT проверяет access (вне диапазона — 404, как у несуществующего id).
VehicleId = Annotated[int, Path(alias="vehicleId")]


@router.get("/vehicle-models", operation_id="searchVehicleModels", **rbac(*ALL_ROLES))
def search_vehicle_models(
    db: DbDep, page: PageDep, search: Annotated[str | None, Query(max_length=100)] = None
) -> VehicleModelList:
    items, meta = paginate(db, service.search_models_stmt(search), page)
    return VehicleModelList(items=items, meta=meta)


@router.get("/vehicles", operation_id="listVehicles", **rbac(UserRole.CLIENT))
def list_vehicles(user: CurrentUser, db: DbDep, page: PageDep) -> VehicleList:
    items, meta = paginate(db, service.list_vehicles_stmt(user), page)
    return VehicleList(items=items, meta=meta)


@router.post(
    "/vehicles",
    operation_id="createVehicle",
    status_code=status.HTTP_201_CREATED,
    **rbac(UserRole.CLIENT),
)
def create_vehicle(
    body: VehicleCreateRequest,
    user: CurrentUser,
    db: DbDep,
    redis: RedisDep,
    settings: SettingsDep,
    decoder: VinDecoderDep,
) -> VehicleOut:
    vehicle = service.create_vehicle(
        db, redis, settings, decoder, user, body.vin, body.vehicle_model_id
    )
    return VehicleOut.model_validate(vehicle)


@router.get("/vehicles/{vehicleId}", operation_id="getVehicle", **rbac(*ALL_ROLES))
def get_vehicle(vehicle_id: VehicleId, user: CurrentUser, db: DbDep) -> VehicleOut:
    return VehicleOut.model_validate(service.get_vehicle(db, user, vehicle_id))


@router.delete(
    "/vehicles/{vehicleId}",
    operation_id="deleteVehicle",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    **rbac(UserRole.CLIENT, UserRole.ADMIN),
)
def delete_vehicle(vehicle_id: VehicleId, user: CurrentUser, db: DbDep) -> Response:
    service.delete_vehicle(db, user, vehicle_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.patch(
    "/vehicles/{vehicleId}/mileage", operation_id="updateVehicleMileage", **rbac(*ALL_ROLES)
)
def update_vehicle_mileage(
    vehicle_id: VehicleId, body: MileageUpdateRequest, user: CurrentUser, db: DbDep
) -> VehicleOut:
    return VehicleOut.model_validate(service.update_mileage(db, user, vehicle_id, body.mileage))


@router.post(
    "/vehicles/{vehicleId}/mileage-corrections",
    operation_id="correctVehicleMileage",
    status_code=status.HTTP_201_CREATED,
    **rbac(UserRole.ADMIN),
)
def correct_vehicle_mileage(
    vehicle_id: VehicleId, body: MileageCorrectionRequest, user: CurrentUser, db: DbDep
) -> VehicleOut:
    vehicle = service.correct_mileage(
        db, user, vehicle_id, body.expected_current_mileage, body.mileage, body.reason
    )
    return VehicleOut.model_validate(vehicle)


@router.get(
    "/vehicles/{vehicleId}/maintenance-records",
    operation_id="listMaintenanceRecords",
    **rbac(*ALL_ROLES),
)
def list_maintenance_records(
    vehicle_id: VehicleId, user: CurrentUser, db: DbDep, page: PageDep
) -> MaintenanceRecordList:
    items, meta = paginate(db, service.list_maintenance_stmt(db, user, vehicle_id), page)
    return MaintenanceRecordList(items=items, meta=meta)


@router.post(
    "/vehicles/{vehicleId}/maintenance-records",
    operation_id="createMaintenanceRecord",
    status_code=status.HTTP_201_CREATED,
    **rbac(*STAFF_ROLES),
)
def create_maintenance_record(
    vehicle_id: VehicleId,
    body: MaintenanceRecordCreateRequest,
    user: CurrentUser,
    db: DbDep,
) -> MaintenanceRecordOut:
    record = service.create_maintenance_record(
        db,
        user,
        vehicle_id,
        aggregate_type_code=body.aggregate_type_code,
        performed_at=body.performed_at,
        mileage_at_service=body.mileage_at_service,
        description=body.description,
    )
    return MaintenanceRecordOut.model_validate(record)
