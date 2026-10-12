"""Глава 14 (#63, ADR 0018): категория, поиск и версии статей, версия источника эскалации.

- knowledge_article.category (ticket_category): категория ошибки, обязательна для
  «устранения неполадок» (п. 2);
- knowledge_article.search_vector: вычисляемый tsvector (russian, заголовок — A, текст — B) + GIN (п. 9);
- knowledge_article_revision: снимок каждой опубликованной редакции, включая дерево решений (п. 1);
- ticket.source_article_version: версия статьи на момент эскалации, составной FK на снимок (п. 11).

Revision ID: 0010
Revises: 0009
Create Date: 2026-10-12
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Тип создан миграцией 0001 (ticket.category).
TICKET_CATEGORY = postgresql.ENUM(
    "navigation",
    "audio",
    "sim",
    "app_crash",
    "maintenance",
    name="ticket_category",
    create_type=False,
)
SEARCH_VECTOR = (
    "setweight(to_tsvector('russian'::regconfig, (title)::text), 'A'::\"char\") || "
    "setweight(to_tsvector('russian'::regconfig, content), 'B'::\"char\")"
)


def upgrade() -> None:
    op.add_column("knowledge_article", sa.Column("category", TICKET_CATEGORY, nullable=True))
    # Статьи до главы 14 не публиковались через API; черновик без категории получает «сбой
    # приложения» — иначе CHECK не создать (на staging и в production статей ещё нет).
    op.execute(
        "UPDATE knowledge_article SET category = 'app_crash' "
        "WHERE article_type = 'troubleshooting' AND category IS NULL"
    )
    op.create_check_constraint(
        op.f("ck_knowledge_article_troubleshooting_has_category"),
        "knowledge_article",
        "article_type <> 'troubleshooting' OR category IS NOT NULL",
    )
    op.add_column(
        "knowledge_article",
        sa.Column(
            "search_vector",
            postgresql.TSVECTOR(),
            sa.Computed(SEARCH_VECTOR, persisted=True),
            nullable=True,
        ),
    )
    op.create_index(
        "ix_knowledge_article_search_vector",
        "knowledge_article",
        ["search_vector"],
        postgresql_using="gin",
    )

    op.create_table(
        "knowledge_article_revision",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("article_id", sa.BigInteger(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("category", TICKET_CATEGORY, nullable=True),
        sa.Column("vehicle_model_id", sa.BigInteger(), nullable=True),
        sa.Column("firmware_release_id", sa.BigInteger(), nullable=True),
        sa.Column(
            "decision_tree",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "jsonb_typeof(decision_tree) = 'array'",
            name=op.f("ck_knowledge_article_revision_decision_tree_is_array"),
        ),
        sa.CheckConstraint(
            "version >= 1", name=op.f("ck_knowledge_article_revision_version_positive")
        ),
        sa.ForeignKeyConstraint(
            ["article_id"],
            ["knowledge_article.id"],
            name=op.f("fk_knowledge_article_revision_article_id_knowledge_article"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["firmware_release_id"],
            ["firmware_release.id"],
            name=op.f("fk_knowledge_article_revision_firmware_release_id_firmware_release"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["vehicle_model_id"],
            ["vehicle_model.id"],
            name=op.f("fk_knowledge_article_revision_vehicle_model_id_vehicle_model"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_knowledge_article_revision")),
        sa.UniqueConstraint(
            "article_id", "version", name=op.f("uq_knowledge_article_revision_article_id_version")
        ),
    )
    op.create_index(
        op.f("ix_knowledge_article_revision_firmware_release_id"),
        "knowledge_article_revision",
        ["firmware_release_id"],
    )
    op.create_index(
        op.f("ix_knowledge_article_revision_vehicle_model_id"),
        "knowledge_article_revision",
        ["vehicle_model_id"],
    )
    # Снимок — история: правится только добавлением (как журнал корректировок пробега, ADR 0006).
    op.execute(
        "CREATE TRIGGER trg_append_only BEFORE UPDATE OR DELETE ON knowledge_article_revision "
        "FOR EACH ROW WHEN (pg_trigger_depth() = 0) EXECUTE FUNCTION append_only_guard()"
    )

    op.add_column("ticket", sa.Column("source_article_version", sa.Integer(), nullable=True))
    op.create_check_constraint(
        op.f("ck_ticket_source_article_version_positive"),
        "ticket",
        "source_article_version >= 1",
    )
    op.create_foreign_key(
        "fk_ticket_source_article_revision",
        "ticket",
        "knowledge_article_revision",
        ["source_article_id", "source_article_version"],
        ["article_id", "version"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint("fk_ticket_source_article_revision", "ticket", type_="foreignkey")
    op.drop_constraint(op.f("ck_ticket_source_article_version_positive"), "ticket", type_="check")
    op.drop_column("ticket", "source_article_version")
    op.execute("DROP TRIGGER IF EXISTS trg_append_only ON knowledge_article_revision")
    op.drop_table("knowledge_article_revision")
    op.drop_index("ix_knowledge_article_search_vector", table_name="knowledge_article")
    op.drop_column("knowledge_article", "search_vector")
    op.drop_constraint(
        op.f("ck_knowledge_article_troubleshooting_has_category"),
        "knowledge_article",
        type_="check",
    )
    # Тип ticket_category остаётся: им пользуется ticket.category (удаляет downgrade 0001).
    op.drop_column("knowledge_article", "category")
