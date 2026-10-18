"""Глава 11 (#50, ADR 0014): seed справочника vehicle_model.

Модели, которые обслуживает ETS AUTO (как в прототипах глав 7–8): Zeekr 001, Voyah Free,
Li Auto L7. Без комплектации (trim = ''). Дальнейшее расширение — админ-панель (Глава 22).

Revision ID: 0006
Revises: 0005
Create Date: 2026-10-11
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

VEHICLE_MODELS: list[tuple[str, str]] = [
    ("Zeekr", "001"),
    ("Voyah", "Free"),
    ("Li Auto", "L7"),
]

vehicle_model = sa.table(
    "vehicle_model",
    sa.column("brand", sa.String),
    sa.column("model", sa.String),
    sa.column("trim", sa.String),
)


def upgrade() -> None:
    op.bulk_insert(vehicle_model, [{"brand": b, "model": m, "trim": ""} for b, m in VEHICLE_MODELS])


def downgrade() -> None:
    # На модель ссылаются авто (FK RESTRICT) — downgrade остановится, данные не удаляются молча.
    for brand, model in VEHICLE_MODELS:
        op.execute(
            vehicle_model.delete().where(
                vehicle_model.c.brand == brand,
                vehicle_model.c.model == model,
                vehicle_model.c.trim == "",
            )
        )
