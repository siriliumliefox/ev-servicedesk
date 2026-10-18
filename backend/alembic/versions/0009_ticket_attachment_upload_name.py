"""Глава 13 (#60, ADR 0017 п. 10): ticket_attachment.upload_name — имя исходной загрузки.

upload_name — {uuid}{расширение} загрузки; UNIQUE: одна загрузка — не более одного вложения.

Revision ID: 0009
Revises: 0008
Create Date: 2026-10-12
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("ticket_attachment", sa.Column("upload_name", sa.String(length=64)))
    # Строки, созданные до колонки: имя — последний сегмент ключа объекта.
    op.execute("UPDATE ticket_attachment SET upload_name = regexp_replace(object_key, '^.*/', '')")
    op.alter_column("ticket_attachment", "upload_name", nullable=False)
    op.create_unique_constraint(
        op.f("uq_ticket_attachment_upload_name"), "ticket_attachment", ["upload_name"]
    )


def downgrade() -> None:
    op.drop_constraint(
        op.f("uq_ticket_attachment_upload_name"), "ticket_attachment", type_="unique"
    )
    op.drop_column("ticket_attachment", "upload_name")
