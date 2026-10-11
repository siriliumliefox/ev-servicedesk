"""Vehicle Service — пути `/vehicles*` и `/vehicle-models` контракта (тег Vehicle, Глава 11).

Прошивка авто (`/vehicles/{id}/firmware`) — тег Notifications; статусы агрегатов — Глава 12.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response, status

from app.api.deps import ALL_ROLES, CurrentUser, DbDep, RedisDep, SettingsDep, rbac
from app.api.pagination import PageDep, paginate
from app.api.vehicle_schemas import (
    MaintenanceRecordCreateRequest,
    MaintenanceRecordList,
    MaintenanceRecordOut,
    MileageCorrectionRequest,
    MileageUpdateRequest,
    VehicleCreateRequest,
    VehicleList,
    VehicleModelList,
    VehicleOut,
    model_out,
    records_out,
    vehicle_out,
    vehicles_out,
)
from app.domain.vehicles import access, service
from app.domain.vehicles.access import Intent
from app.domain.vehicles.vin import MockVinDecoder, VinDecoder
from app.models.enums import UserRole

router = APIRouter(tags=["Vehicle"])

STAFF = (UserRole.ENGINEER, UserRole.ADMIN)


def get_vin_decoder() -> VinDecoder:
    """Seam декодера: внешний API (X-05) подключается здесь, тесты подменяют зависимость."""
    return MockVinDecoder()


VinDecoderDep = Annotated[VinDecoder, Depends(get_vin_decoder)]


@router.get("/vehicle-models", operation_id="searchVehicleModels", **rbac(*ALL_ROLES))
def search_vehicle_models(
    db: DbDep, page: PageDep, search: Annotated[str | None, Query(max_length=100)] = None
) -> VehicleModelList:
    items, meta = paginate(db, service.search_models_stmt(search), page)
    return VehicleModelList(items=[model_out(m) for m in items], meta=meta)


@router.get("/vehicles", operation_id="listVehicles", **rbac(UserRole.CLIENT))
def list_vehicles(user: CurrentUser, db: DbDep, page: PageDep) -> VehicleList:
    items, meta = paginate(db, service.list_vehicles_stmt(user), page)
    return VehicleList(items=vehicles_out(db, items), meta=meta)


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
    return vehicle_out(db, vehicle)


@router.get("/vehicles/{vehicleId}", operation_id="getVehicle", **rbac(*ALL_ROLES))
def get_vehicle(vehicleId: int, user: CurrentUser, db: DbDep) -> VehicleOut:  # noqa: N803
    return vehicle_out(db, access.get_vehicle(db, user, vehicleId, Intent.VIEW))


@router.delete(
    "/vehicles/{vehicleId}",
    operation_id="deleteVehicle",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    **rbac(UserRole.CLIENT, UserRole.ADMIN),
)
def delete_vehicle(vehicleId: int, user: CurrentUser, db: DbDep) -> Response:  # noqa: N803
    service.delete_vehicle(db, user, vehicleId)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.patch(
    "/vehicles/{vehicleId}/mileage", operation_id="updateVehicleMileage", **rbac(*ALL_ROLES)
)
def update_vehicle_mileage(
    vehicleId: int,  # noqa: N803
    body: MileageUpdateRequest,
    user: CurrentUser,
    db: DbDep,
) -> VehicleOut:
    return vehicle_out(db, service.update_mileage(db, user, vehicleId, body.mileage))


@router.post(
    "/vehicles/{vehicleId}/mileage-corrections",
    operation_id="correctVehicleMileage",
    status_code=status.HTTP_201_CREATED,
    **rbac(UserRole.ADMIN),
)
def correct_vehicle_mileage(
    vehicleId: int,  # noqa: N803
    body: MileageCorrectionRequest,
    user: CurrentUser,
    db: DbDep,
) -> VehicleOut:
    vehicle = service.correct_mileage(
        db, user, vehicleId, body.expected_current_mileage, body.mileage, body.reason
    )
    return vehicle_out(db, vehicle)


@router.get(
    "/vehicles/{vehicleId}/maintenance-records",
    operation_id="listMaintenanceRecords",
    response_model_exclude_unset=True,
    **rbac(*ALL_ROLES),
)
def list_maintenance_records(
    vehicleId: int,  # noqa: N803
    user: CurrentUser,
    db: DbDep,
    page: PageDep,
) -> MaintenanceRecordList:
    items, meta = paginate(db, service.list_maintenance_stmt(db, user, vehicleId), page)
    return MaintenanceRecordList(items=records_out(db, items), meta=meta)


@router.post(
    "/vehicles/{vehicleId}/maintenance-records",
    operation_id="createMaintenanceRecord",
    status_code=status.HTTP_201_CREATED,
    response_model_exclude_unset=True,
    **rbac(*STAFF),
)
def create_maintenance_record(
    vehicleId: int,  # noqa: N803
    body: MaintenanceRecordCreateRequest,
    user: CurrentUser,
    db: DbDep,
) -> MaintenanceRecordOut:
    record = service.create_maintenance_record(
        db,
        user,
        vehicleId,
        aggregate_type_code=body.aggregate_type_code,
        performed_at=body.performed_at,
        mileage_at_service=body.mileage_at_service,
        description=body.description,
    )
    return records_out(db, [record])[0]
