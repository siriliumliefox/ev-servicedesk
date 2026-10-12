"""Сценарии Knowledge Base Service (Глава 14, ADR 0018). Видимость статей — `access`.

Версия — опубликованная редакция (п. 1): снимок (`KnowledgeArticleRevision`) создаётся, когда
после записи статья опубликована, а её содержание (заголовок, текст, категория, привязка,
дерево) отличается от последнего снимка. Дерево опубликованной статьи не меняется (п. 5),
поэтому живое дерево опубликованной статьи совпадает со снимком её текущей версии.
Записи статьи и её дерева идут по очереди под блокировкой строки статьи (п. 7).
"""

import unicodedata
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from sqlalchemy import Select, func, literal, select
from sqlalchemy.dialects.postgresql import REGCONFIG
from sqlalchemy.orm import Session

from app.core.db import get_by_id, is_db_id
from app.core.errors import ApiError, field_error
from app.domain.knowledge import access
from app.domain.knowledge.tree import TreeIssue, TreeNode, validate_tree
from app.models import (
    AppUser,
    DecisionTreeNode,
    FirmwareRelease,
    KnowledgeArticle,
    KnowledgeArticleRevision,
    VehicleModel,
)
from app.models.enums import KbArticleType, TicketCategory, UserRole

MAX_NODES = 100  # узлов в дереве (ADR 0018 п. 3)
SNAPSHOT_FIELDS = ("title", "content", "category", "vehicle_model_id", "firmware_release_id")


# ---------- Список и карточка ----------


def list_articles_stmt(
    user: AppUser,
    *,
    vehicle_model_id: int | None = None,
    article_type: KbArticleType | None = None,
    category: TicketCategory | None = None,
    is_published: bool | None = None,
    search: str | None = None,
) -> Select:
    """GET /knowledge-articles: фильтры сужают видимую выборку (ADR 0018 п. 9).

    Фильтр по модели включает общие статьи; `is_published` учитывается только для персонала.
    С `search` — по релевантности полнотекстового поиска, без — свежие правки первыми.
    """
    stmt = select(KnowledgeArticle).where(access.visible(user))
    if vehicle_model_id is not None:
        stmt = stmt.where(
            (KnowledgeArticle.vehicle_model_id == vehicle_model_id)
            | KnowledgeArticle.vehicle_model_id.is_(None)
        )
    if article_type is not None:
        stmt = stmt.where(KnowledgeArticle.article_type == article_type)
    if category is not None:
        stmt = stmt.where(KnowledgeArticle.category == category)
    if is_published is not None and user.role is not UserRole.CLIENT:
        stmt = stmt.where(KnowledgeArticle.is_published.is_(is_published))
    # NFC — как текст статей (схемы запросов): иначе «й» из двух кодов не находит «й».
    search = unicodedata.normalize("NFC", (search or "").strip())
    if not search:
        return stmt.order_by(KnowledgeArticle.updated_at.desc(), KnowledgeArticle.id.desc())
    query = func.websearch_to_tsquery(literal("russian", REGCONFIG), search)
    return stmt.where(KnowledgeArticle.search_vector.bool_op("@@")(query)).order_by(
        func.ts_rank(KnowledgeArticle.search_vector, query).desc(), KnowledgeArticle.id
    )


def get_article(db: Session, user: AppUser, article_id: int) -> KnowledgeArticle:
    return access.get_article(db, user, article_id)


# ---------- Статьи: создание и правка (admin) ----------


def _check_binding(db: Session, vehicle_model_id: int | None, firmware_release_id: int | None):
    """Модель существует; прошивка — той же модели (C-06), без модели прошивки нет."""
    if vehicle_model_id is not None and get_by_id(db, VehicleModel, vehicle_model_id) is None:
        raise field_error("vehicle_model_id", "VEHICLE_MODEL_NOT_FOUND", "Модель не найдена")
    if firmware_release_id is None:
        return
    firmware = get_by_id(db, FirmwareRelease, firmware_release_id)
    if firmware is None or firmware.vehicle_model_id != vehicle_model_id:
        raise field_error(
            "firmware_release_id",
            "FIRMWARE_RELEASE_NOT_FOUND",
            "Прошивка не найдена у модели статьи",
        )


def _check_category(article_type: KbArticleType, category: TicketCategory | None) -> None:
    if article_type is KbArticleType.TROUBLESHOOTING and category is None:
        raise field_error(
            "category",
            "CATEGORY_REQUIRED",
            "У статьи «устранение неполадок» должна быть категория ошибки",
        )


def create_article(
    db: Session,
    *,
    article_type: KbArticleType,
    title: str,
    content: str,
    category: TicketCategory | None,
    vehicle_model_id: int | None,
    firmware_release_id: int | None,
) -> KnowledgeArticle:
    """POST /knowledge-articles (admin): черновик без версий (ADR 0018 п. 1)."""
    _check_category(article_type, category)
    _check_binding(db, vehicle_model_id, firmware_release_id)
    article = KnowledgeArticle(
        article_type=article_type,
        title=title,
        content=content,
        category=category,
        vehicle_model_id=vehicle_model_id,
        firmware_release_id=firmware_release_id,
    )
    db.add(article)
    return _commit(db, article)


def _commit[M](db: Session, row: M) -> M:
    """Запись и COMMIT; ответ — состояние своей записи (updated_at ставит триггер БД,
    ADR 0006), а не перечитанное после COMMIT, где уже может быть чужая правка.
    """
    db.flush()
    db.refresh(row)
    db.commit()
    return row


def update_article(db: Session, article_id: int, changes: Mapping[str, Any]) -> KnowledgeArticle:
    """PATCH /knowledge-articles/{id} (admin): правка и публикация (ADR 0018 п. 1, 5).

    `changes` — только переданные поля. Публикация «устранения неполадок» — только с
    валидным деревом (409 DECISION_TREE_INVALID). Если после записи статья опубликована и её
    содержание отличается от последней версии — новая версия со снимком.
    """
    article = access.for_change(db, article_id)
    values = {f: changes.get(f, getattr(article, f)) for f in (*SNAPSHOT_FIELDS, "is_published")}
    # Все проверки — до изменения объекта: отказ не оставляет в сессии полузаписанную статью,
    # а запрос проверки не сбрасывает в БД (autoflush) запись, нарушающую FK (500 вместо 422).
    _check_category(article.article_type, values["category"])
    if "vehicle_model_id" in changes or "firmware_release_id" in changes:
        _check_binding(db, values["vehicle_model_id"], values["firmware_release_id"])
    nodes = _nodes(db, article.id) if values["is_published"] else []
    publishing = values["is_published"] and not article.is_published
    if publishing and article.article_type is KbArticleType.TROUBLESHOOTING:
        issues = validate_tree([_tree_node(n) for n in nodes])
        if issues:
            raise ApiError(
                409,
                "DECISION_TREE_INVALID",
                "Дерево решений с ошибками — исправьте их перед публикацией",
                details={"issues": [issue_out(i) for i in issues]},
            )

    for field, value in values.items():
        setattr(article, field, value)
    if article.is_published:
        _record_version(db, article, nodes)
    return _commit(db, article)


def unpublish_article(db: Session, article_id: int) -> None:
    """DELETE /knowledge-articles/{id} (admin): снять с публикации; повтор — тоже 204.

    Версии и ссылки тикетов сохраняются (ADR 0018 п. 11).
    """
    article = access.for_change(db, article_id)
    article.is_published = False
    db.commit()


# ---------- Версии ----------


def _snapshot_tree(nodes: Sequence[DecisionTreeNode]) -> list[dict[str, Any]]:
    return [
        {
            "id": n.id,
            "question_text": n.question_text,
            "options": n.options,
            "is_root": n.is_root,
            "is_escalation": n.is_escalation,
        }
        for n in nodes
    ]


def _last_revision(db: Session, article_id: int) -> KnowledgeArticleRevision | None:
    return db.scalars(
        select(KnowledgeArticleRevision)
        .where(KnowledgeArticleRevision.article_id == article_id)
        .order_by(KnowledgeArticleRevision.version.desc())
        .limit(1)
    ).one_or_none()


def _record_version(
    db: Session, article: KnowledgeArticle, nodes: Sequence[DecisionTreeNode]
) -> None:
    """Снимок опубликованной статьи, если содержание отличается от последней версии."""
    snapshot = {f: getattr(article, f) for f in SNAPSHOT_FIELDS}
    snapshot["decision_tree"] = _snapshot_tree(nodes)
    last = _last_revision(db, article.id)
    if last is not None and all(getattr(last, k) == v for k, v in snapshot.items()):
        return
    version = 1 if last is None else last.version + 1
    db.add(KnowledgeArticleRevision(article_id=article.id, version=version, **snapshot))
    article.version = version


def list_revisions_stmt(db: Session, user: AppUser, article_id: int) -> Select:
    """GET /knowledge-articles/{id}/revisions (engineer/admin): новые версии первыми."""
    article = access.get_with_history(db, user, article_id)
    return (
        select(KnowledgeArticleRevision)
        .where(KnowledgeArticleRevision.article_id == article.id)
        .order_by(KnowledgeArticleRevision.version.desc())
    )


def get_revision(
    db: Session, user: AppUser, article_id: int, version: int
) -> KnowledgeArticleRevision:
    """GET /knowledge-articles/{id}/revisions/{version} (engineer/admin)."""
    article = access.get_with_history(db, user, article_id)
    revision = db.scalars(
        select(KnowledgeArticleRevision).where(
            KnowledgeArticleRevision.article_id == article.id,
            KnowledgeArticleRevision.version == version,
        )
    ).one_or_none()
    if revision is None:
        raise ApiError(404, "NOT_FOUND", "Версия статьи не найдена")
    return revision


# ---------- Дерево решений ----------


def _nodes(db: Session, article_id: int) -> list[DecisionTreeNode]:
    return list(db.scalars(_nodes_stmt(article_id)))


def _nodes_stmt(article_id: int) -> Select:
    return (
        select(DecisionTreeNode)
        .where(DecisionTreeNode.article_id == article_id)
        .order_by(DecisionTreeNode.id)
    )


def _tree_node(node: DecisionTreeNode) -> TreeNode:
    return TreeNode(
        id=node.id,
        next_ids=tuple(o["next_node_id"] for o in node.options),
        is_root=node.is_root,
        is_escalation=node.is_escalation,
    )


def issue_out(issue: TreeIssue) -> dict[str, Any]:
    """Проблема дерева в ответе: без node_id — проблема дерева целиком."""
    out: dict[str, Any] = {"problem": issue.problem.value}
    if issue.node_id is not None:
        out["node_id"] = issue.node_id
    return out


def list_nodes_stmt(db: Session, user: AppUser, article_id: int) -> Select:
    """GET /knowledge-articles/{id}/decision-tree: узлы видимой статьи по порядку создания."""
    article = access.get_article(db, user, article_id)
    return _nodes_stmt(article.id)


def validate(db: Session, article_id: int) -> list[TreeIssue]:
    """GET /knowledge-articles/{id}/decision-tree/validate (admin — видит и черновики).

    У «руководства» дерева нет — проверять нечего, проблем нет.
    """
    article = get_by_id(db, KnowledgeArticle, article_id)
    if article is None:
        raise access.not_found()
    if article.article_type is not KbArticleType.TROUBLESHOOTING:
        return []
    return validate_tree([_tree_node(n) for n in _nodes(db, article.id)])


@dataclass(frozen=True)
class NodeInput:
    question_text: str
    options: Sequence[tuple[str, int]]  # (label, next_node_id)
    is_root: bool
    is_escalation: bool


def _article_for_tree(db: Session, article_id: int) -> KnowledgeArticle:
    """Статья под блокировкой, дерево которой можно менять (ADR 0018 п. 5)."""
    article = access.for_change(db, article_id)
    if article.article_type is not KbArticleType.TROUBLESHOOTING:
        raise ApiError(
            409, "ARTICLE_TYPE_HAS_NO_TREE", "Дерево решений есть только у «устранения неполадок»"
        )
    if article.is_published:
        raise ApiError(
            409,
            "ARTICLE_PUBLISHED",
            "Дерево опубликованной статьи не меняется — сначала снимите её с публикации",
        )
    return article


def _check_node(data: NodeInput, siblings: Sequence[DecisionTreeNode], node_id: int | None) -> None:
    """Корень единственный (409), переходы — только на узлы этой статьи (422)."""
    if data.is_root and any(n.is_root and n.id != node_id for n in siblings):
        raise ApiError(
            409,
            "DECISION_TREE_ROOT_EXISTS",
            "У дерева уже есть корень — сначала снимите признак с прежнего",
        )
    known = {n.id for n in siblings}
    for i, (_, next_id) in enumerate(data.options):
        if next_id not in known:
            raise ApiError(
                422,
                "INVALID_NEXT_NODE",
                "Вариант ведёт на узел, которого нет в дереве этой статьи",
                details={"fields": [{"loc": ["body", "options", i, "next_node_id"]}]},
            )


def _options(data: NodeInput) -> list[dict[str, Any]]:
    return [{"label": label, "next_node_id": next_id} for label, next_id in data.options]


def create_node(db: Session, article_id: int, data: NodeInput) -> DecisionTreeNode:
    """POST /knowledge-articles/{id}/decision-tree (admin)."""
    article = _article_for_tree(db, article_id)
    siblings = _nodes(db, article.id)
    if len(siblings) >= MAX_NODES:
        raise ApiError(
            422, "DECISION_TREE_TOO_LARGE", f"В дереве не может быть больше {MAX_NODES} узлов"
        )
    _check_node(data, siblings, None)
    node = DecisionTreeNode(
        article_id=article.id,
        question_text=data.question_text,
        options=_options(data),
        is_root=data.is_root,
        is_escalation=data.is_escalation,
    )
    db.add(node)
    db.commit()
    return node


def _node_or_404(db: Session, node_id: int) -> DecisionTreeNode:
    node = get_by_id(db, DecisionTreeNode, node_id, populate_existing=True)
    if node is None:
        raise ApiError(404, "NOT_FOUND", "Узел дерева решений не найден")
    return node


def update_node(db: Session, node_id: int, data: NodeInput) -> DecisionTreeNode:
    """PATCH /decision-tree-nodes/{id} (admin): узел заменяется целиком."""
    article = _article_for_tree(db, _node_or_404(db, node_id).article_id)
    node = _node_or_404(db, node_id)  # под блокировкой статьи: мог быть удалён
    _check_node(data, _nodes(db, article.id), node.id)
    node.question_text = data.question_text
    node.options = _options(data)
    node.is_root = data.is_root
    node.is_escalation = data.is_escalation
    return _commit(db, node)


def delete_node(db: Session, node_id: int) -> None:
    """DELETE /decision-tree-nodes/{id} (admin): узел, на который ссылаются другие, — 409.

    Ссылка тикета на узел (эскалация) обнуляется (FK SET NULL), версия статьи остаётся.
    """
    article = _article_for_tree(db, _node_or_404(db, node_id).article_id)
    node = _node_or_404(db, node_id)
    referenced_by = [
        n.id
        for n in _nodes(db, article.id)
        if n.id != node.id and any(o["next_node_id"] == node.id for o in n.options)
    ]
    if referenced_by:
        raise ApiError(
            409,
            "DECISION_TREE_NODE_REFERENCED",
            "На узел ссылаются другие узлы — сначала измените их варианты",
            details={"referenced_by": referenced_by},
        )
    db.delete(node)
    db.commit()


# ---------- Эскалация в тикет ----------


def escalation_version(db: Session, article_id: int | None, node_id: int | None) -> int | None:
    """Версия статьи для тикета, эскалированного из дерева решений (ADR 0018 п. 11).

    Статья — с хотя бы одной опубликованной версией (сейчас может быть снята с публикации);
    узел, если указан, — узел эскалации этой статьи. Иначе 422 INVALID_SOURCE_REFERENCE —
    одинаково для отсутствующей статьи и черновика без версий (не оракул черновиков).
    Узел блокируется FOR SHARE: удаление узла и смена его типа ждут создания тикета — тикет
    не ссылается на удалённый узел (FK) и на узел, переставший быть эскалацией.
    """
    if article_id is None:
        if node_id is not None:
            raise _source_error("Узел дерева решений указан без статьи")
        return None
    version = None
    if is_db_id(article_id):
        version = db.scalar(
            select(func.max(KnowledgeArticleRevision.version)).where(
                KnowledgeArticleRevision.article_id == article_id
            )
        )
    if version is None:
        raise _source_error("Статья базы знаний не найдена")
    if node_id is None:
        return version
    node = None
    if is_db_id(node_id):
        node = db.scalars(
            select(DecisionTreeNode)
            .where(DecisionTreeNode.id == node_id)
            .with_for_update(read=True)
        ).one_or_none()
    if node is None or node.article_id != article_id or not node.is_escalation:
        raise _source_error("Узел эскалации не найден в указанной статье")
    return version


def _source_error(message: str) -> ApiError:
    return field_error("source_article_id", "INVALID_SOURCE_REFERENCE", message)
