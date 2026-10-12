"""Глава 16 (#69, ADR 0020): витрина аналитики — materialized view фактов и учёт обновлений.

- analytics_ticket_fact: строка на тикет — дата создания по Минску, модель, категория, часы до
  первичного ответа и до решения, «решён с просрочкой», есть ли работа ТО по тикету (п. 1, 5, 7);
- analytics_reminder_fact: строка на пару «напоминание о ТО, получатель» — открыто ли, была ли
  работа ТО по авто в течение 30 дней (п. 1, 8);
- analytics_vehicle_model_fact: активные авто модели (п. 6);
- analytics_refresh: время последнего обновления каждой витрины (`computed_at`, п. 3).

Витрины создаются заполненными (WITH DATA, п. 2); уникальные индексы нужны для
REFRESH ... CONCURRENTLY. Обновляет `analytics-worker`.

Revision ID: 0013
Revises: 0012
Create Date: 2026-10-12
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0013"
down_revision: str | None = "0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Период аналитики — по времени Минска (ADR 0020 п. 4), как BUSINESS_TZ приложения.
TZ = "Europe/Minsk"
HOURS = "EXTRACT(EPOCH FROM ({end} - t.created_at)) / 3600"

VIEWS = {
    "analytics_ticket_fact": f"""
        SELECT t.id AS ticket_id,
               (t.created_at AT TIME ZONE '{TZ}')::date AS created_on,
               v.vehicle_model_id,
               t.category,
               {HOURS.format(end="t.first_response_at")} AS first_response_hours,
               {HOURS.format(end="t.resolved_at")} AS resolution_hours,
               t.resolved_at IS NOT NULL AND t.resolved_at > t.sla_due_at AS resolved_overdue,
               EXISTS (SELECT 1 FROM maintenance_record m WHERE m.ticket_id = t.id)
                   AS has_maintenance
        FROM ticket t
        JOIN vehicle v ON v.id = t.vehicle_id
    """,
    "analytics_reminder_fact": f"""
        SELECT f.recipient_id, f.created_on, f.vehicle_model_id,
               EXISTS (
                   SELECT 1
                   FROM notification_delivery d
                   JOIN push_token p ON p.id = d.push_token_id
                   WHERE d.notification_id = f.notification_id
                     AND p.user_id = f.user_id
                     AND d.opened_at IS NOT NULL
               ) AS opened,
               EXISTS (
                   SELECT 1
                   FROM maintenance_record m
                   WHERE m.vehicle_id = f.vehicle_id
                     AND m.performed_at BETWEEN f.created_on AND f.created_on + 30
               ) AS has_maintenance
        FROM (
            SELECT r.id AS recipient_id, r.user_id, n.id AS notification_id, n.vehicle_id,
                   (n.created_at AT TIME ZONE '{TZ}')::date AS created_on,
                   v.vehicle_model_id
            FROM notification n
            JOIN notification_recipient r ON r.notification_id = n.id
            JOIN vehicle v ON v.id = n.vehicle_id
            WHERE n.type = 'maintenance'
        ) f
    """,
    "analytics_vehicle_model_fact": """
        SELECT vm.id AS vehicle_model_id,
               count(v.id) FILTER (WHERE v.deleted_at IS NULL) AS vehicles_total
        FROM vehicle_model vm
        LEFT JOIN vehicle v ON v.vehicle_model_id = vm.id
        GROUP BY vm.id
    """,
}

INDEXES = {
    "analytics_ticket_fact": [
        "CREATE UNIQUE INDEX uq_analytics_ticket_fact_ticket_id "
        "ON analytics_ticket_fact (ticket_id)",
        "CREATE INDEX ix_analytics_ticket_fact_created_on "
        "ON analytics_ticket_fact (created_on, vehicle_model_id)",
    ],
    "analytics_reminder_fact": [
        "CREATE UNIQUE INDEX uq_analytics_reminder_fact_recipient_id "
        "ON analytics_reminder_fact (recipient_id)",
        "CREATE INDEX ix_analytics_reminder_fact_created_on "
        "ON analytics_reminder_fact (created_on, vehicle_model_id)",
    ],
    "analytics_vehicle_model_fact": [
        "CREATE UNIQUE INDEX uq_analytics_vehicle_model_fact_vehicle_model_id "
        "ON analytics_vehicle_model_fact (vehicle_model_id)",
    ],
}


def upgrade() -> None:
    op.create_table(
        "analytics_refresh",
        sa.Column("view_name", sa.String(length=63), nullable=False),
        sa.Column("refreshed_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("view_name", name=op.f("pk_analytics_refresh")),
    )
    for name, query in VIEWS.items():
        op.execute(f"CREATE MATERIALIZED VIEW {name} AS {query} WITH DATA")
        for ddl in INDEXES[name]:
            op.execute(ddl)
        op.execute(
            f"INSERT INTO analytics_refresh (view_name, refreshed_at) "
            f"VALUES ('{name}', clock_timestamp())"
        )


def downgrade() -> None:
    for name in reversed(VIEWS):
        op.execute(f"DROP MATERIALIZED VIEW {name}")
    op.drop_table("analytics_refresh")
