"""Глава 24 (#116, ADR 0028 п. 15): индекс списка рассылок администратора.

listPublishedNotifications фильтрует type IN ('firmware', 'news', 'promo') и сортирует по
created_at, id. Без индекса каждый вызов читал всю таблицу notification — вместе с
напоминаниями о ТО, которые копятся каждый день (тест планов tests/api/test_query_plans.py).
Частичный индекс содержит только рассылки: их единицы в неделю.

Revision ID: 0015
Revises: 0014
Create Date: 2026-10-15
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0015"
down_revision: str | None = "0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_index(
        "ix_notification_published",
        "notification",
        [sa.text("created_at DESC"), sa.text("id DESC")],
        postgresql_where=sa.text("type IN ('firmware', 'news', 'promo')"),
    )


def downgrade() -> None:
    op.drop_index("ix_notification_published", table_name="notification")
