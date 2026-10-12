"""Knowledge Base: статьи, версии и деревья решений (C-06, C-07, E-03, A-02; ADR 0018)."""

from typing import Any

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Computed,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, TSVECTOR
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, CreatedAtMixin, IdMixin, TimestampMixin
from app.models.enums import KbArticleType, TicketCategory, pg_enum

# Полнотекстовый поиск (ADR 0018 п. 9): заголовок важнее текста.
SEARCH_VECTOR = (
    "setweight(to_tsvector('russian'::regconfig, (title)::text), 'A'::\"char\") || "
    "setweight(to_tsvector('russian'::regconfig, content), 'B'::\"char\")"
)


class KnowledgeArticle(IdMixin, TimestampMixin, Base):
    """vehicle_model_id NULL = общая статья; firmware_release_id — статья под версию (C-06).

    version — номер последней опубликованной редакции; у черновика без публикаций — 1, а
    снимков нет (ADR 0018 п. 1). category — категория ошибки (= категория тикета), обязательна
    для «устранения неполадок».
    """

    __tablename__ = "knowledge_article"
    __table_args__ = (
        CheckConstraint("version >= 1", name="version_positive"),
        CheckConstraint("btrim(title) <> ''", name="title_not_blank"),
        CheckConstraint(
            "firmware_release_id IS NULL OR vehicle_model_id IS NOT NULL",
            name="firmware_requires_model",
        ),
        CheckConstraint(
            "article_type <> 'troubleshooting' OR category IS NOT NULL",
            name="troubleshooting_has_category",
        ),
        ForeignKeyConstraint(
            ["firmware_release_id", "vehicle_model_id"],
            ["firmware_release.id", "firmware_release.vehicle_model_id"],
            name="fk_knowledge_article_firmware_same_model",
            ondelete="RESTRICT",
        ),
        Index("ix_knowledge_article_search_vector", "search_vector", postgresql_using="gin"),
    )

    vehicle_model_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("vehicle_model.id", ondelete="RESTRICT"), index=True
    )
    firmware_release_id: Mapped[int | None] = mapped_column(BigInteger, index=True)
    article_type: Mapped[KbArticleType] = mapped_column(
        pg_enum(KbArticleType, "kb_article_type"), nullable=False
    )
    category: Mapped[TicketCategory | None] = mapped_column(
        pg_enum(TicketCategory, "ticket_category")
    )
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    content: Mapped[str] = mapped_column(Text, server_default=text("''"), nullable=False)
    version: Mapped[int] = mapped_column(Integer, server_default=text("1"), nullable=False)
    is_published: Mapped[bool] = mapped_column(server_default=text("false"), nullable=False)
    # Пишет только PostgreSQL; при выборке колонка не нужна — deferred.
    search_vector: Mapped[Any] = mapped_column(
        TSVECTOR, Computed(SEARCH_VECTOR, persisted=True), deferred=True
    )


class KnowledgeArticleRevision(IdMixin, CreatedAtMixin, Base):
    """Снимок опубликованной редакции статьи (ADR 0018 п. 1); только добавляется.

    decision_tree — узлы дерева на момент публикации ([{id, question_text, options, is_root,
    is_escalation}]); created_at — момент публикации версии.
    """

    __tablename__ = "knowledge_article_revision"
    __table_args__ = (
        UniqueConstraint("article_id", "version"),
        CheckConstraint("version >= 1", name="version_positive"),
        CheckConstraint("jsonb_typeof(decision_tree) = 'array'", name="decision_tree_is_array"),
    )

    article_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("knowledge_article.id", ondelete="CASCADE"), nullable=False
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    category: Mapped[TicketCategory | None] = mapped_column(
        pg_enum(TicketCategory, "ticket_category")
    )
    vehicle_model_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("vehicle_model.id", ondelete="RESTRICT"), index=True
    )
    firmware_release_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("firmware_release.id", ondelete="RESTRICT"), index=True
    )
    decision_tree: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, server_default=text("'[]'::jsonb"), nullable=False
    )


class DecisionTreeNode(IdMixin, TimestampMixin, Base):
    """options = [{label, next_node_id}] в JSONB — осознанное отступление от 1НФ (ADR 0003).

    Ссылочную целостность next_node_id проверяет сервис при сохранении узла и
    validateDecisionTree (ADR 0018 п. 3–4).
    """

    __tablename__ = "decision_tree_node"
    __table_args__ = (
        CheckConstraint("jsonb_typeof(options) = 'array'", name="options_is_array"),
        Index(
            "uq_decision_tree_node_root",
            "article_id",
            unique=True,
            postgresql_where=text("is_root = true"),
        ),
    )

    article_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("knowledge_article.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    question_text: Mapped[str] = mapped_column(Text, nullable=False)
    options: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, server_default=text("'[]'::jsonb"), nullable=False
    )
    is_root: Mapped[bool] = mapped_column(server_default=text("false"), nullable=False)
    is_escalation: Mapped[bool] = mapped_column(server_default=text("false"), nullable=False)
