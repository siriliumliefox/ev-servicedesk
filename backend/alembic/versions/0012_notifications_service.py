"""Глава 15 (#66, ADR 0019): очередь push, мягкий отзыв токенов, напоминания о ТО.

- push_token: revoked_at, уникальность токена только среди активных, длина токена 1024 (п. 8);
- notification_delivery: attempts, next_attempt_at, failed_at, error_code + индекс очереди (п. 2, 9);
- notification: vehicle_id, aggregate_type_id — у напоминания о ТО и только у него (п. 6, 12);
- aggregate_status_thresholds: reminder_before_km, reminder_before_days — порог N (N-10, п. 5);
- maintenance_reminder: учёт напоминаний на цикл замены, NULLS NOT DISTINCT (п. 6).

Revision ID: 0012
Revises: 0011
Create Date: 2026-10-12
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0012"
down_revision: str | None = "0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

REMINDER_KIND = postgresql.ENUM("due_soon", "overdue", name="maintenance_reminder_kind")
PENDING = "delivered_at IS NULL AND failed_at IS NULL"


def upgrade() -> None:
    # --- push_token ---
    op.add_column("push_token", sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True))
    op.drop_constraint(op.f("uq_push_token_token"), "push_token", type_="unique")
    op.alter_column(
        "push_token",
        "token",
        existing_type=sa.String(length=255),
        type_=sa.String(length=1024),
        existing_nullable=False,
    )
    op.create_index(
        "uq_push_token_token_active",
        "push_token",
        ["token"],
        unique=True,
        postgresql_where=sa.text("revoked_at IS NULL"),
    )

    # --- notification_delivery ---
    op.add_column(
        "notification_delivery",
        sa.Column("attempts", sa.SmallInteger(), server_default=sa.text("0"), nullable=False),
    )
    op.add_column(
        "notification_delivery",
        sa.Column(
            "next_attempt_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.add_column(
        "notification_delivery",
        sa.Column("failed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "notification_delivery", sa.Column("error_code", sa.String(length=50), nullable=True)
    )
    op.create_check_constraint(
        op.f("ck_notification_delivery_delivered_or_failed"),
        "notification_delivery",
        "delivered_at IS NULL OR failed_at IS NULL",
    )
    op.create_check_constraint(
        op.f("ck_notification_delivery_attempts_non_negative"),
        "notification_delivery",
        "attempts >= 0",
    )
    op.create_index(
        "ix_notification_delivery_pending",
        "notification_delivery",
        ["next_attempt_at", "id"],
        postgresql_where=sa.text(PENDING),
    )

    # --- notification ---
    op.add_column("notification", sa.Column("vehicle_id", sa.BigInteger(), nullable=True))
    op.add_column("notification", sa.Column("aggregate_type_id", sa.BigInteger(), nullable=True))
    op.create_foreign_key(
        op.f("fk_notification_vehicle_id_vehicle"),
        "notification",
        "vehicle",
        ["vehicle_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        op.f("fk_notification_aggregate_type_id_aggregate_type"),
        "notification",
        "aggregate_type",
        ["aggregate_type_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_index(op.f("ix_notification_vehicle_id"), "notification", ["vehicle_id"])
    op.create_index(
        op.f("ix_notification_aggregate_type_id"), "notification", ["aggregate_type_id"]
    )
    # Напоминаний о ТО до главы 15 не создавалось (API не было).
    op.create_check_constraint(
        op.f("ck_notification_maintenance_target"),
        "notification",
        "(type = 'maintenance') = (vehicle_id IS NOT NULL) "
        "AND (vehicle_id IS NULL) = (aggregate_type_id IS NULL)",
    )

    # --- aggregate_status_thresholds ---
    op.add_column(
        "aggregate_status_thresholds",
        sa.Column(
            "reminder_before_km", sa.Integer(), server_default=sa.text("1000"), nullable=False
        ),
    )
    op.add_column(
        "aggregate_status_thresholds",
        sa.Column(
            "reminder_before_days",
            sa.SmallInteger(),
            server_default=sa.text("14"),
            nullable=False,
        ),
    )
    op.create_check_constraint(
        op.f("ck_aggregate_status_thresholds_reminder_range"),
        "aggregate_status_thresholds",
        "reminder_before_km BETWEEN 1 AND 100000 AND reminder_before_days BETWEEN 1 AND 365",
    )

    # --- maintenance_reminder ---
    op.create_table(
        "maintenance_reminder",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("vehicle_id", sa.BigInteger(), nullable=False),
        sa.Column("aggregate_type_id", sa.BigInteger(), nullable=False),
        sa.Column("kind", REMINDER_KIND, nullable=False),
        sa.Column("cycle_replaced_at", sa.Date(), nullable=True),
        sa.Column("cycle_replaced_mileage", sa.Integer(), nullable=True),
        sa.Column("notification_id", sa.BigInteger(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["aggregate_type_id"],
            ["aggregate_type.id"],
            name=op.f("fk_maintenance_reminder_aggregate_type_id_aggregate_type"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["notification_id"],
            ["notification.id"],
            name=op.f("fk_maintenance_reminder_notification_id_notification"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["vehicle_id"],
            ["vehicle.id"],
            name=op.f("fk_maintenance_reminder_vehicle_id_vehicle"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_maintenance_reminder")),
        sa.UniqueConstraint(
            "vehicle_id",
            "aggregate_type_id",
            "kind",
            "cycle_replaced_at",
            "cycle_replaced_mileage",
            name="uq_maintenance_reminder_cycle",
            postgresql_nulls_not_distinct=True,
        ),
    )
    op.create_index(
        op.f("ix_maintenance_reminder_aggregate_type_id"),
        "maintenance_reminder",
        ["aggregate_type_id"],
    )
    op.create_index(
        op.f("ix_maintenance_reminder_notification_id"),
        "maintenance_reminder",
        ["notification_id"],
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_maintenance_reminder_notification_id"), table_name="maintenance_reminder"
    )
    op.drop_index(
        op.f("ix_maintenance_reminder_aggregate_type_id"), table_name="maintenance_reminder"
    )
    op.drop_table("maintenance_reminder")
    REMINDER_KIND.drop(op.get_bind(), checkfirst=False)

    op.drop_constraint(
        op.f("ck_aggregate_status_thresholds_reminder_range"),
        "aggregate_status_thresholds",
        type_="check",
    )
    op.drop_column("aggregate_status_thresholds", "reminder_before_days")
    op.drop_column("aggregate_status_thresholds", "reminder_before_km")

    # Напоминания о ТО появились в главе 15 — схема до неё их не допускает.
    op.execute("DELETE FROM notification WHERE type = 'maintenance' AND vehicle_id IS NOT NULL")
    op.drop_constraint(op.f("ck_notification_maintenance_target"), "notification", type_="check")
    op.drop_index(op.f("ix_notification_aggregate_type_id"), table_name="notification")
    op.drop_index(op.f("ix_notification_vehicle_id"), table_name="notification")
    op.drop_constraint(
        op.f("fk_notification_aggregate_type_id_aggregate_type"), "notification", type_="foreignkey"
    )
    op.drop_constraint(
        op.f("fk_notification_vehicle_id_vehicle"), "notification", type_="foreignkey"
    )
    op.drop_column("notification", "aggregate_type_id")
    op.drop_column("notification", "vehicle_id")

    op.drop_index("ix_notification_delivery_pending", table_name="notification_delivery")
    op.drop_constraint(
        op.f("ck_notification_delivery_attempts_non_negative"),
        "notification_delivery",
        type_="check",
    )
    op.drop_constraint(
        op.f("ck_notification_delivery_delivered_or_failed"),
        "notification_delivery",
        type_="check",
    )
    op.drop_column("notification_delivery", "error_code")
    op.drop_column("notification_delivery", "failed_at")
    op.drop_column("notification_delivery", "next_attempt_at")
    op.drop_column("notification_delivery", "attempts")

    # До главы 15 токен уникален целиком и не длиннее 255: отозванные строки и длинные токены
    # удаляются (их доставки — каскадом), иначе UNIQUE и VARCHAR(255) не восстановить.
    op.execute("DELETE FROM push_token WHERE revoked_at IS NOT NULL OR length(token) > 255")
    op.drop_index("uq_push_token_token_active", table_name="push_token")
    op.alter_column(
        "push_token",
        "token",
        existing_type=sa.String(length=1024),
        type_=sa.String(length=255),
        existing_nullable=False,
    )
    op.create_unique_constraint(op.f("uq_push_token_token"), "push_token", ["token"])
    op.drop_column("push_token", "revoked_at")
