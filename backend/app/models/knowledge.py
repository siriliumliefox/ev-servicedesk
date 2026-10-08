"""Knowledge Base: статьи и деревья решений (C-06, C-07, E-03, A-02)."""

from typing import Any

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, IdMixin, TimestampMixin
from app.models.enums import KbArticleType, pg_enum


class KnowledgeArticle(IdMixin, TimestampMixin, Base):
    """vehicle_model_id NULL = общая статья; firmware_release_id — статья под версию (C-06)."""

    __tablename__ = "knowledge_article"
    __table_args__ = (
        CheckConstraint("version >= 1", name="version_positive"),
        CheckConstraint("btrim(title) <> ''", name="title_not_blank"),
        CheckConstraint(
            "firmware_release_id IS NULL OR vehicle_model_id IS NOT NULL",
            name="firmware_requires_model",
        ),
        ForeignKeyConstraint(
            ["firmware_release_id", "vehicle_model_id"],
            ["firmware_release.id", "firmware_release.vehicle_model_id"],
            name="fk_knowledge_article_firmware_same_model",
            ondelete="RESTRICT",
        ),
    )

    vehicle_model_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("vehicle_model.id", ondelete="RESTRICT"), index=True
    )
    firmware_release_id: Mapped[int | None] = mapped_column(BigInteger, index=True)
    article_type: Mapped[KbArticleType] = mapped_column(
        pg_enum(KbArticleType, "kb_article_type"), nullable=False
    )
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    content: Mapped[str] = mapped_column(Text, server_default=text("''"), nullable=False)
    version: Mapped[int] = mapped_column(Integer, server_default=text("1"), nullable=False)
    is_published: Mapped[bool] = mapped_column(server_default=text("false"), nullable=False)


class DecisionTreeNode(IdMixin, TimestampMixin, Base):
    """options = [{label, next_node_id}] в JSONB — осознанное отступление от 1НФ (ADR 0003).

    Ссылочную целостность next_node_id проверяет validateDecisionTree (Глава 14).
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
