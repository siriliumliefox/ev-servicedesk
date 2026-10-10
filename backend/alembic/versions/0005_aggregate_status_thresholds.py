"""Глава 5 (#31, ADR 0009): пороги «светофора», настраиваемые администратором.

- aggregate_status_thresholds: ровно одна строка (id = 1) с 70/100 по умолчанию;
  удалить её нельзя (триггер singleton_row_guard), менять — только UPDATE;
- updated_at обновляет общий триггер set_updated_at (ADR 0006).

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-10
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "aggregate_status_thresholds",
        sa.Column(
            "id",
            sa.SmallInteger(),
            server_default=sa.text("1"),
            autoincrement=False,
            nullable=False,
        ),
        sa.Column(
            "yellow_from_percent", sa.SmallInteger(), server_default=sa.text("70"), nullable=False
        ),
        sa.Column(
            "red_above_percent", sa.SmallInteger(), server_default=sa.text("100"), nullable=False
        ),
        sa.Column("updated_by_user_id", sa.BigInteger(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("id = 1", name=op.f("ck_aggregate_status_thresholds_singleton")),
        sa.CheckConstraint(
            "yellow_from_percent >= 1 AND yellow_from_percent < red_above_percent "
            "AND red_above_percent <= 200",
            name=op.f("ck_aggregate_status_thresholds_percent_order"),
        ),
        sa.ForeignKeyConstraint(
            ["updated_by_user_id"],
            ["app_user.id"],
            name=op.f("fk_aggregate_status_thresholds_updated_by_user_id_app_user"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_aggregate_status_thresholds")),
    )
    op.create_index(
        op.f("ix_aggregate_status_thresholds_updated_by_user_id"),
        "aggregate_status_thresholds",
        ["updated_by_user_id"],
        unique=False,
    )
    op.execute("INSERT INTO aggregate_status_thresholds (id) VALUES (1)")
    op.execute(
        "CREATE TRIGGER trg_set_updated_at BEFORE UPDATE ON aggregate_status_thresholds "
        "FOR EACH ROW EXECUTE FUNCTION set_updated_at()"
    )
    op.execute(
        """
        CREATE FUNCTION singleton_row_guard() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION '% row cannot be deleted', TG_TABLE_NAME
                USING ERRCODE = 'check_violation', CONSTRAINT = TG_TABLE_NAME || '_singleton';
        END;
        $$
        """
    )
    op.execute(
        "CREATE TRIGGER trg_singleton_row_guard BEFORE DELETE ON aggregate_status_thresholds "
        "FOR EACH ROW EXECUTE FUNCTION singleton_row_guard()"
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_singleton_row_guard ON aggregate_status_thresholds")
    op.execute("DROP FUNCTION IF EXISTS singleton_row_guard()")
    op.execute("DROP TRIGGER IF EXISTS trg_set_updated_at ON aggregate_status_thresholds")
    op.drop_index(
        op.f("ix_aggregate_status_thresholds_updated_by_user_id"),
        table_name="aggregate_status_thresholds",
    )
    op.drop_table("aggregate_status_thresholds")
