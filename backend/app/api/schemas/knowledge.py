"""Схемы Knowledge Base — по components/schemas docs/openapi.yaml 1.5.0 (ADR 0007, ADR 0018).

Пределы текста (ADR 0018 п. 10) проверяют валидаторы, а не maxLength контракта: новый maxLength
в запросе `oasdiff` считает ломающим (как длины тикетов, ADR 0017 п. 13). Текст приводится
к Unicode NFC — как весь текст репозитория и справочники.
"""

import unicodedata
from datetime import datetime
from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.api.pagination import PaginationMeta
from app.api.schemas.common import no_control_chars, no_control_chars_multiline
from app.core.db import BIGINT_MAX
from app.domain.knowledge.tree import TreeProblem
from app.models import KnowledgeArticleRevision
from app.models.enums import KbArticleType, TicketCategory

TITLE_MAX = 200
CONTENT_MAX = 50_000
QUESTION_MAX = 1000
LABEL_MAX = 100
OPTIONS_MAX = 10

DbId = Annotated[int, Field(ge=1, le=BIGINT_MAX)]


def _nfc(value: str) -> str:
    return unicodedata.normalize("NFC", value)


def _line(value: str, max_length: int) -> str:
    """Однострочный текст: обрезка пробелов, 1…max_length символов, без управляющих."""
    value = _nfc(no_control_chars(value.strip()))
    if not value:
        raise ValueError("текст не может быть пустым")
    if len(value) > max_length:
        raise ValueError(f"не больше {max_length} символов")
    return value


def _content(value: str) -> str:
    """Markdown статьи хранится как есть (отступы значимы), без обрезки пробелов."""
    value = _nfc(no_control_chars_multiline(value))
    if len(value) > CONTENT_MAX:
        raise ValueError(f"не больше {CONTENT_MAX} символов")
    return value


class KnowledgeArticleCreateRequest(BaseModel):
    vehicle_model_id: DbId | None = None
    firmware_release_id: DbId | None = None
    article_type: KbArticleType
    category: TicketCategory | None = None
    title: str
    content: str

    _check_title = field_validator("title")(lambda v: _line(v, TITLE_MAX))
    _check_content = field_validator("content")(_content)


class KnowledgeArticleUpdateRequest(BaseModel):
    """PATCH: меняются только переданные поля (`model_fields_set`); null — снять привязку."""

    title: str | None = None
    content: str | None = None
    category: TicketCategory | None = None
    vehicle_model_id: DbId | None = None
    firmware_release_id: DbId | None = None
    is_published: bool | None = None

    @field_validator("title")
    @classmethod
    def _title(cls, value: str | None) -> str | None:
        return None if value is None else _line(value, TITLE_MAX)

    @field_validator("content")
    @classmethod
    def _content(cls, value: str | None) -> str | None:
        return None if value is None else _content(value)

    @model_validator(mode="after")
    def _not_null(self) -> "KnowledgeArticleUpdateRequest":
        for field in ("title", "content", "is_published"):
            if field in self.model_fields_set and getattr(self, field) is None:
                raise ValueError(f"{field} не может быть null")
        return self

    def changes(self) -> dict[str, Any]:
        return {f: getattr(self, f) for f in self.model_fields_set}


class DecisionTreeOption(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    label: str
    next_node_id: DbId

    _check_label = field_validator("label")(lambda v: _line(v, LABEL_MAX))


class DecisionTreeNodeCreateRequest(BaseModel):
    question_text: str
    options: list[DecisionTreeOption] = []
    is_root: bool
    is_escalation: bool

    @field_validator("question_text")
    @classmethod
    def _question(cls, value: str) -> str:
        value = _nfc(no_control_chars_multiline(value.strip()))
        if not value:
            raise ValueError("текст не может быть пустым")
        if len(value) > QUESTION_MAX:
            raise ValueError(f"не больше {QUESTION_MAX} символов")
        return value

    @field_validator("options")
    @classmethod
    def _options(cls, value: list[DecisionTreeOption]) -> list[DecisionTreeOption]:
        if len(value) > OPTIONS_MAX:
            raise ValueError(f"не больше {OPTIONS_MAX} вариантов")
        labels = [o.label for o in value]
        if len(set(labels)) != len(labels):
            raise ValueError("варианты ответа узла не должны повторяться")
        return value


# ---------- Ответы ----------


class KnowledgeArticleOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    vehicle_model_id: int | None
    firmware_release_id: int | None
    article_type: KbArticleType
    category: TicketCategory | None
    title: str
    content: str
    version: int
    is_published: bool
    updated_at: datetime


class KnowledgeArticleList(BaseModel):
    items: list[KnowledgeArticleOut]
    meta: PaginationMeta


class DecisionTreeNodeOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    article_id: int
    question_text: str
    options: list[DecisionTreeOption]
    is_root: bool
    is_escalation: bool


class DecisionTreeNodeList(BaseModel):
    items: list[DecisionTreeNodeOut]
    meta: PaginationMeta


class DecisionTreeIssue(BaseModel):
    """Без node_id — проблема дерева целиком (NO_ROOT, NO_ESCALATION)."""

    node_id: int | None = Field(default=None, exclude_if=lambda v: v is None)
    problem: TreeProblem


class DecisionTreeValidationResult(BaseModel):
    is_valid: bool
    issues: list[DecisionTreeIssue]


class KnowledgeArticleRevisionSummary(BaseModel):
    version: int
    title: str
    published_at: datetime


class KnowledgeArticleRevisionList(BaseModel):
    items: list[KnowledgeArticleRevisionSummary]
    meta: PaginationMeta


class KnowledgeArticleRevisionOut(KnowledgeArticleRevisionSummary):
    article_id: int
    content: str
    category: TicketCategory | None
    vehicle_model_id: int | None
    firmware_release_id: int | None
    decision_tree: list[DecisionTreeNodeOut]


def revision_summary_out(revision: KnowledgeArticleRevision) -> KnowledgeArticleRevisionSummary:
    return KnowledgeArticleRevisionSummary(
        version=revision.version, title=revision.title, published_at=revision.created_at
    )


def revision_out(revision: KnowledgeArticleRevision) -> KnowledgeArticleRevisionOut:
    """Узлы снимка хранятся без article_id — он один на всю версию."""
    return KnowledgeArticleRevisionOut(
        **dict(revision_summary_out(revision)),
        article_id=revision.article_id,
        content=revision.content,
        category=revision.category,
        vehicle_model_id=revision.vehicle_model_id,
        firmware_release_id=revision.firmware_release_id,
        decision_tree=[
            DecisionTreeNodeOut.model_validate({**node, "article_id": revision.article_id})
            for node in revision.decision_tree
        ],
    )
