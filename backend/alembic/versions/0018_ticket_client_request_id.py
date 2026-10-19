"""#111 (ADR 0031): ключ повтора создания тикета и сообщения чата.

Клиент передаёт `client_request_id` (UUID черновика) и повторяет запрос с тем же ключом после
обрыва связи: сервер, уже записавший тикет или сообщение, возвращает записанное, а не создаёт
дубль. UNIQUE — граница области ключа: тикет — авто (владелец авто неизменяем, ADR 0003),
сообщение — тикет и автор. Без ключа (NULL) — прежнее поведение: NULL в UNIQUE не совпадают.

Revision ID: 0018
Revises: 0017
Create Date: 2026-10-19
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0018"
down_revision: str | None = "0017"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("ticket", sa.Column("client_request_id", sa.Uuid(), nullable=True))
    op.create_unique_constraint(
        "uq_ticket_vehicle_id_client_request_id", "ticket", ["vehicle_id", "client_request_id"]
    )
    op.add_column("ticket_message", sa.Column("client_request_id", sa.Uuid(), nullable=True))
    op.create_unique_constraint(
        "uq_ticket_message_ticket_id_author_id_client_request_id",
        "ticket_message",
        ["ticket_id", "author_id", "client_request_id"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_ticket_message_ticket_id_author_id_client_request_id", "ticket_message", type_="unique"
    )
    op.drop_column("ticket_message", "client_request_id")
    op.drop_constraint("uq_ticket_vehicle_id_client_request_id", "ticket", type_="unique")
    op.drop_column("ticket", "client_request_id")
