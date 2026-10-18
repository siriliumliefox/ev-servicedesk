"""Глава 25 (#120, ADR 0029 п. 18): анонимизация VIN при отзыве согласия ПД.

VIN неизменяем (`vehicle_guard`, техдолг ADR 0005 / 99-З п. 14а). Анонимизация заменяет VIN
удалённого авто на 17 нулей: формат (CHECK) и контракт (строка из 17 символов) сохраняются,
уникальность действует только для активных авто. Иные изменения VIN по-прежнему запрещены;
анонимизированное авто не восстанавливается (deleted_at не снимается).

Revision ID: 0016
Revises: 0015
Create Date: 2026-10-18
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0016"
down_revision: str | None = "0015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ANONYMIZED_VIN = "00000000000000000"

# Предыдущая версия функции — VEHICLE_GUARD_V2 миграции 0004 (для downgrade).
VEHICLE_GUARD_V2 = """
CREATE OR REPLACE FUNCTION vehicle_guard() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF NEW.vin IS DISTINCT FROM OLD.vin
       OR NEW.user_id IS DISTINCT FROM OLD.user_id
       OR NEW.vehicle_model_id IS DISTINCT FROM OLD.vehicle_model_id THEN
        RAISE EXCEPTION 'vehicle vin, user_id and vehicle_model_id are immutable'
            USING ERRCODE = 'check_violation', CONSTRAINT = 'vehicle_identity_immutable';
    END IF;
    IF NEW.mileage < OLD.mileage AND NOT EXISTS (
        SELECT 1 FROM vehicle_mileage_correction c
        WHERE c.vehicle_id = NEW.id
          AND c.old_mileage = OLD.mileage
          AND c.new_mileage = NEW.mileage
          AND c.created_at = now()
    ) THEN
        RAISE EXCEPTION 'vehicle mileage cannot decrease without an admin correction'
            USING ERRCODE = 'check_violation', CONSTRAINT = 'vehicle_mileage_monotonic';
    END IF;
    RETURN NEW;
END;
$$
"""

VEHICLE_GUARD_V3 = f"""
CREATE OR REPLACE FUNCTION vehicle_guard() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF (NEW.vin IS DISTINCT FROM OLD.vin
            AND NOT (NEW.vin = '{ANONYMIZED_VIN}' AND NEW.deleted_at IS NOT NULL))
       OR NEW.user_id IS DISTINCT FROM OLD.user_id
       OR NEW.vehicle_model_id IS DISTINCT FROM OLD.vehicle_model_id THEN
        RAISE EXCEPTION 'vehicle vin, user_id and vehicle_model_id are immutable'
            USING ERRCODE = 'check_violation', CONSTRAINT = 'vehicle_identity_immutable';
    END IF;
    IF OLD.vin = '{ANONYMIZED_VIN}' AND NEW.deleted_at IS NULL THEN
        RAISE EXCEPTION 'anonymized vehicle cannot be restored'
            USING ERRCODE = 'check_violation', CONSTRAINT = 'vehicle_anonymized_final';
    END IF;
    IF NEW.mileage < OLD.mileage AND NOT EXISTS (
        SELECT 1 FROM vehicle_mileage_correction c
        WHERE c.vehicle_id = NEW.id
          AND c.old_mileage = OLD.mileage
          AND c.new_mileage = NEW.mileage
          AND c.created_at = now()
    ) THEN
        RAISE EXCEPTION 'vehicle mileage cannot decrease without an admin correction'
            USING ERRCODE = 'check_violation', CONSTRAINT = 'vehicle_mileage_monotonic';
    END IF;
    RETURN NEW;
END;
$$
"""


def upgrade() -> None:
    op.execute(VEHICLE_GUARD_V3)


def downgrade() -> None:
    # Анонимизированные авто остаются с нулевым VIN: восстановить исходный нельзя (ПД удалены).
    op.execute(VEHICLE_GUARD_V2)
