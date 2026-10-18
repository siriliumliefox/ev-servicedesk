"""Глава 25 (#120, #102, ADR 0029 п. 12): момент отзыва всех сессий пользователя.

Access-токен, выпущенный раньше `sessions_revoked_at`, не принимается: сброс и смена пароля,
блокировка, отзыв согласия и повторное предъявление refresh завершают выданные access-токены
сразу, а не через 15 минут. Отметка ставится в той же транзакции, что и отзыв refresh-токенов;
`get_current_user` и WebSocket и так читают строку пользователя.

Revision ID: 0017
Revises: 0016
Create Date: 2026-10-18
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0017"
down_revision: str | None = "0016"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "app_user", sa.Column("sessions_revoked_at", sa.DateTime(timezone=True), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("app_user", "sessions_revoked_at")
