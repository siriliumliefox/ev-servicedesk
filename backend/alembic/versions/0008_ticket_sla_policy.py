"""Глава 13 (#60, ADR 0017 п. 1–2): нормативы SLA — срок решения тикета по категории.

- ticket_sla_policy: категория → минуты; seed — утверждённые нормативы (app_crash 4 ч,
  navigation и sim 8 ч, audio 24 ч, maintenance 48 ч); API нет — изменение только миграцией;
- updated_at обновляет общий триггер set_updated_at (ADR 0006).

Revision ID: 0008
Revises: 0007
Create Date: 2026-10-11
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Минуты: срок решения считается календарно, 24/7 (ADR 0017 п. 1).
SLA_RESOLUTION_MINUTES = {
    "app_crash": 4 * 60,
    "navigation": 8 * 60,
    "sim": 8 * 60,
    "audio": 24 * 60,
    "maintenance": 48 * 60,
}


def upgrade() -> None:
    op.create_table(
        "ticket_sla_policy",
        sa.Column(
            "category",
            # Тип создан миграцией 0001.
            postgresql.ENUM(
                "navigation",
                "audio",
                "sim",
                "app_crash",
                "maintenance",
                name="ticket_category",
                create_type=False,
            ),
            nullable=False,
        ),
        sa.Column("resolution_minutes", sa.Integer(), nullable=False),
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
        sa.CheckConstraint(
            "resolution_minutes > 0", name=op.f("ck_ticket_sla_policy_resolution_minutes_positive")
        ),
        sa.PrimaryKeyConstraint("category", name=op.f("pk_ticket_sla_policy")),
    )
    values = ", ".join(f"('{c}', {m})" for c, m in SLA_RESOLUTION_MINUTES.items())
    op.execute(f"INSERT INTO ticket_sla_policy (category, resolution_minutes) VALUES {values}")
    op.execute(
        "CREATE TRIGGER trg_set_updated_at BEFORE UPDATE ON ticket_sla_policy "
        "FOR EACH ROW EXECUTE FUNCTION set_updated_at()"
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_set_updated_at ON ticket_sla_policy")
    # Тип ticket_category остаётся: им пользуется ticket.category (удаляет downgrade 0001).
    op.drop_table("ticket_sla_policy")
