"""Глава 2 (follow-up #13): полный индекс FK maintenance_regulation.vehicle_model_id.

Частичный uq_maintenance_regulation_active не покрывает архивные регламенты, поэтому
RESTRICT-проверка при удалении vehicle_model и JOIN по модели читали бы всю таблицу.

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-08
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_index(
        op.f("ix_maintenance_regulation_vehicle_model_id"),
        "maintenance_regulation",
        ["vehicle_model_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_maintenance_regulation_vehicle_model_id"), table_name="maintenance_regulation"
    )
