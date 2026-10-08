"""Глава 2: seed базового справочника aggregate_type (baseline v1, ADR 0002).

Коды утверждены владельцем 2026-10-08 (docs/requirements/BACKLOG.md). Дальнейшее
расширение — через админ-панель (A-07), не через миграции.

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-08
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

AGGREGATE_TYPES: list[tuple[str, str]] = [
    ("engine_oil", "Масло двигателя"),
    ("oil_filter", "Масляный фильтр"),
    ("air_filter", "Воздушный фильтр"),
    ("cabin_filter", "Салонный фильтр"),
    ("gearbox_oil", "Масло редуктора"),
    ("ac_refrigerant", "Фреон кондиционера"),
]

aggregate_type = sa.table(
    "aggregate_type",
    sa.column("code", sa.String),
    sa.column("name", sa.String),
)


def upgrade() -> None:
    op.bulk_insert(aggregate_type, [{"code": c, "name": n} for c, n in AGGREGATE_TYPES])


def downgrade() -> None:
    # Если на тип уже ссылаются регламенты/статусы/история, FK RESTRICT остановит
    # downgrade — это намеренно: данные не удаляются молча.
    op.execute(
        aggregate_type.delete().where(aggregate_type.c.code.in_([c for c, _ in AGGREGATE_TYPES]))
    )
