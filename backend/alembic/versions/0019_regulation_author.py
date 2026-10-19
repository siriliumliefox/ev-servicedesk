"""#105 (U-44, ADR 0034): автор версии регламента ТО.

Дата версии уже есть (`created_at`); автор — администратор, создавший версию. У версий до
миграции автора нет (NULL). ON DELETE RESTRICT, как у прочих ссылок на пользователя: учётные
записи не удаляются, ПД анонимизируются на месте (ADR 0029).

Revision ID: 0019
Revises: 0018
Create Date: 2026-10-19
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0019"
down_revision: str | None = "0018"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "maintenance_regulation", sa.Column("created_by_user_id", sa.BigInteger(), nullable=True)
    )
    op.create_foreign_key(
        "fk_maintenance_regulation_created_by_user_id_app_user",
        "maintenance_regulation",
        "app_user",
        ["created_by_user_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_index(
        "ix_maintenance_regulation_created_by_user_id",
        "maintenance_regulation",
        ["created_by_user_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_maintenance_regulation_created_by_user_id", "maintenance_regulation")
    op.drop_constraint(
        "fk_maintenance_regulation_created_by_user_id_app_user",
        "maintenance_regulation",
        type_="foreignkey",
    )
    op.drop_column("maintenance_regulation", "created_by_user_id")
