"""ORM-модели пишут и читают данные в схеме миграций (ENUM хранит value, дефолты БД)."""

from datetime import UTC, date, datetime, timedelta

from sqlalchemy import Connection, select, text
from sqlalchemy.orm import Session

from app.models import (
    AggregateType,
    AppUser,
    FirmwareRelease,
    MaintenanceRecord,
    Ticket,
    TicketAttachment,
    TicketMessage,
    Vehicle,
    VehicleAggregateStatus,
    VehicleModel,
)
from app.models.enums import AttachmentType, TicketCategory, TicketStatus, UserRole
from tests.db.factories import fake_phone, fake_vin


def test_orm_roundtrip(conn: Connection) -> None:
    with Session(bind=conn, join_transaction_mode="create_savepoint") as s:
        client = AppUser(phone=fake_phone(), role=UserRole.CLIENT)
        engineer = AppUser(phone=fake_phone(), role=UserRole.ENGINEER, password_hash="$argon2id$t")
        model = VehicleModel(brand="ORMBrand", model="ORMModel")
        s.add_all([client, engineer, model])
        s.flush()
        fw = FirmwareRelease(
            vehicle_model_id=model.id, version="2.4.1", released_at=date(2026, 9, 1)
        )
        s.add(fw)
        s.flush()
        vehicle = Vehicle(
            user_id=client.id,
            vehicle_model_id=model.id,
            vin=fake_vin(),
            current_firmware_release_id=fw.id,
        )
        s.add(vehicle)
        s.flush()
        oil = s.scalar(select(AggregateType).where(AggregateType.code == "engine_oil"))
        assert oil is not None
        s.add(VehicleAggregateStatus(vehicle_id=vehicle.id, aggregate_type_id=oil.id))
        ticket = Ticket(
            vehicle_id=vehicle.id,
            category=TicketCategory.APP_CRASH,
            description="Приложение закрывается",
            sla_due_at=datetime.now(UTC) + timedelta(minutes=15),
            firmware_release_id=fw.id,
        )
        s.add(ticket)
        s.flush()
        message = TicketMessage(ticket_id=ticket.id, author_id=client.id, body="Скриншот")
        s.add(message)
        s.flush()
        s.add(
            TicketAttachment(
                ticket_id=ticket.id,
                ticket_message_id=message.id,
                object_key=f"tickets/{ticket.id}/screen.png",
                file_type=AttachmentType.PHOTO,
                mime_type="image/png",
                size_bytes=2048,
                uploaded_by_user_id=client.id,
            )
        )
        s.add(
            MaintenanceRecord(
                vehicle_id=vehicle.id,
                aggregate_type_id=oil.id,
                performed_by_user_id=engineer.id,
                ticket_id=ticket.id,
                performed_at=date(2026, 10, 1),
                mileage_at_service=0,
            )
        )
        s.flush()
        s.refresh(ticket)
        s.refresh(vehicle)

        assert ticket.status is TicketStatus.NEW
        assert vehicle.mileage == 0
        assert vehicle.created_at is not None and vehicle.deleted_at is None
        # ENUM хранит value, а не имя члена (проверка до отката savepoint сессии).
        raw = s.execute(text("SELECT category::text FROM ticket WHERE id = :t"), {"t": ticket.id})
        assert raw.scalar_one() == "app_crash"
