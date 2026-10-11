"""Глава 12 (#55, ADR 0016): названия агрегатов seed 0002 — в форме Unicode NFC.

Seed 0002 записал часть названий в разложенной форме (NFD: «и» + U+0306 вместо «й»):
API отдавал их клиентам, сравнение и поиск по названию не совпадали с набранным текстом.
Новые названия нормализует схема запроса `AggregateTypeCreateRequest`.

Revision ID: 0007
Revises: 0006
Create Date: 2026-10-11
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        "UPDATE aggregate_type SET name = normalize(name, NFC) WHERE name IS NOT NFC NORMALIZED"
    )


def downgrade() -> None:
    # Намеренно без обратного преобразования: NFC и NFD — один и тот же текст, а вернуть
    # «исходную» форму для строк, добавленных после upgrade, нельзя. Схема не менялась.
    pass
