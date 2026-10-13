"""Глава 19 (#79, ADR 0023 п. 2): вид записи истории ТО — замена агрегата или работа.

- maintenance_record.kind: replacement — запись создана заменой агрегата (replaceAggregateStatus),
  work — прочая работа (createMaintenanceRecord: осмотр, долив, работа без агрегата);
- замена всегда по агрегату (CHECK);
- существующие строки — work: production-данных нет, а восстановить признак по
  vehicle_aggregate_status.last_replaced_* нельзя надёжно (замены задним числом, повторы).

Revision ID: 0014
Revises: 0013
Create Date: 2026-10-12
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0014"
down_revision: str | None = "0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

RECORD_KIND = postgresql.ENUM("replacement", "work", name="maintenance_record_kind")


def upgrade() -> None:
    RECORD_KIND.create(op.get_bind(), checkfirst=False)
    op.add_column(
        "maintenance_record",
        sa.Column("kind", RECORD_KIND, server_default="work", nullable=False),
    )
    op.create_check_constraint(
        op.f("ck_maintenance_record_replacement_has_aggregate"),
        "maintenance_record",
        "kind <> 'replacement' OR aggregate_type_id IS NOT NULL",
    )


def downgrade() -> None:
    op.drop_constraint(
        op.f("ck_maintenance_record_replacement_has_aggregate"), "maintenance_record", type_="check"
    )
    op.drop_column("maintenance_record", "kind")
    RECORD_KIND.drop(op.get_bind(), checkfirst=False)
