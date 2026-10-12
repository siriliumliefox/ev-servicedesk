"""Knowledge Base Service — тег KnowledgeBase контракта (Глава 14, ADR 0018).

Статьи с привязкой к модели и категории ошибки, версии (опубликованные редакции), дерево
решений с проверкой тупиков; эскалация из дерева — `createTicket` (тег Tickets).
"""

from typing import Annotated

from fastapi import APIRouter, Path, Query, Response, status
from pydantic import AfterValidator

from app.api.deps import ALL_ROLES, CurrentUser, DbDep, rbac
from app.api.pagination import PageDep, paginate
from app.api.schemas.knowledge import (
    DecisionTreeIssue,
    DecisionTreeNodeCreateRequest,
    DecisionTreeNodeList,
    DecisionTreeNodeOut,
    DecisionTreeValidationResult,
    KnowledgeArticleCreateRequest,
    KnowledgeArticleList,
    KnowledgeArticleOut,
    KnowledgeArticleRevisionList,
    KnowledgeArticleRevisionOut,
    KnowledgeArticleUpdateRequest,
    revision_out,
    revision_summary_out,
    search_query,
)
from app.core.db import BIGINT_MAX
from app.domain.knowledge import service
from app.models.enums import KbArticleType, TicketCategory, UserRole

router = APIRouter(tags=["KnowledgeBase"])

STAFF = (UserRole.ENGINEER, UserRole.ADMIN)
SEARCH_MAX = 200  # длина запроса поиска (ADR 0018 п. 9) — проверка сервера

# Диапазон BIGINT проверяют access и сервис (вне диапазона — 404, как у несуществующего id).
ArticleId = Annotated[int, Path(alias="articleId")]
NodeId = Annotated[int, Path(alias="nodeId")]


def _node_input(body: DecisionTreeNodeCreateRequest) -> service.NodeInput:
    return service.NodeInput(
        question_text=body.question_text,
        options=[(o.label, o.next_node_id) for o in body.options],
        is_root=body.is_root,
        is_escalation=body.is_escalation,
    )


# ---------- Статьи ----------


@router.get("/knowledge-articles", operation_id="listKnowledgeArticles", **rbac(*ALL_ROLES))
def list_knowledge_articles(
    user: CurrentUser,
    db: DbDep,
    page: PageDep,
    # Диапазон BIGINT: вне его — ошибка драйвера и 500, а не 422.
    vehicle_model_id: Annotated[int | None, Query(ge=-BIGINT_MAX - 1, le=BIGINT_MAX)] = None,
    article_type: KbArticleType | None = None,
    category: TicketCategory | None = None,
    is_published: bool | None = None,
    search: Annotated[
        str | None, Query(max_length=SEARCH_MAX), AfterValidator(search_query)
    ] = None,
) -> KnowledgeArticleList:
    stmt = service.list_articles_stmt(
        user,
        vehicle_model_id=vehicle_model_id,
        article_type=article_type,
        category=category,
        is_published=is_published,
        search=search,
    )
    items, meta = paginate(db, stmt, page)
    return KnowledgeArticleList(
        items=[KnowledgeArticleOut.model_validate(a) for a in items], meta=meta
    )


@router.post(
    "/knowledge-articles",
    operation_id="createKnowledgeArticle",
    status_code=status.HTTP_201_CREATED,
    **rbac(UserRole.ADMIN),
)
def create_knowledge_article(body: KnowledgeArticleCreateRequest, db: DbDep) -> KnowledgeArticleOut:
    article = service.create_article(
        db,
        article_type=body.article_type,
        title=body.title,
        content=body.content,
        category=body.category,
        vehicle_model_id=body.vehicle_model_id,
        firmware_release_id=body.firmware_release_id,
    )
    return KnowledgeArticleOut.model_validate(article)


@router.get(
    "/knowledge-articles/{articleId}", operation_id="getKnowledgeArticle", **rbac(*ALL_ROLES)
)
def get_knowledge_article(
    article_id: ArticleId, user: CurrentUser, db: DbDep
) -> KnowledgeArticleOut:
    return KnowledgeArticleOut.model_validate(service.get_article(db, user, article_id))


@router.patch(
    "/knowledge-articles/{articleId}",
    operation_id="updateKnowledgeArticle",
    **rbac(UserRole.ADMIN),
)
def update_knowledge_article(
    article_id: ArticleId, body: KnowledgeArticleUpdateRequest, db: DbDep
) -> KnowledgeArticleOut:
    article = service.update_article(db, article_id, body.changes())
    return KnowledgeArticleOut.model_validate(article)


@router.delete(
    "/knowledge-articles/{articleId}",
    operation_id="unpublishKnowledgeArticle",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    **rbac(UserRole.ADMIN),
)
def unpublish_knowledge_article(article_id: ArticleId, db: DbDep) -> Response:
    service.unpublish_article(db, article_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ---------- Версии ----------


@router.get(
    "/knowledge-articles/{articleId}/revisions",
    operation_id="listKnowledgeArticleRevisions",
    **rbac(*STAFF),
)
def list_knowledge_article_revisions(
    article_id: ArticleId, user: CurrentUser, db: DbDep, page: PageDep
) -> KnowledgeArticleRevisionList:
    items, meta = paginate(db, service.list_revisions_stmt(db, user, article_id), page)
    return KnowledgeArticleRevisionList(items=[revision_summary_out(r) for r in items], meta=meta)


@router.get(
    "/knowledge-articles/{articleId}/revisions/{version}",
    operation_id="getKnowledgeArticleRevision",
    **rbac(*STAFF),
)
def get_knowledge_article_revision(
    article_id: ArticleId,
    version: Annotated[int, Path(ge=1, le=2_147_483_647)],
    user: CurrentUser,
    db: DbDep,
) -> KnowledgeArticleRevisionOut:
    return revision_out(service.get_revision(db, user, article_id, version))


# ---------- Дерево решений ----------


@router.get(
    "/knowledge-articles/{articleId}/decision-tree",
    operation_id="listDecisionTreeNodes",
    **rbac(*ALL_ROLES),
)
def list_decision_tree_nodes(
    article_id: ArticleId, user: CurrentUser, db: DbDep, page: PageDep
) -> DecisionTreeNodeList:
    items, meta = paginate(db, service.list_nodes_stmt(db, user, article_id), page)
    return DecisionTreeNodeList(
        items=[DecisionTreeNodeOut.model_validate(n) for n in items], meta=meta
    )


@router.post(
    "/knowledge-articles/{articleId}/decision-tree",
    operation_id="createDecisionTreeNode",
    status_code=status.HTTP_201_CREATED,
    **rbac(UserRole.ADMIN),
)
def create_decision_tree_node(
    article_id: ArticleId, body: DecisionTreeNodeCreateRequest, db: DbDep
) -> DecisionTreeNodeOut:
    node = service.create_node(db, article_id, _node_input(body))
    return DecisionTreeNodeOut.model_validate(node)


@router.get(
    "/knowledge-articles/{articleId}/decision-tree/validate",
    operation_id="validateDecisionTree",
    **rbac(UserRole.ADMIN),
)
def validate_decision_tree(article_id: ArticleId, db: DbDep) -> DecisionTreeValidationResult:
    issues = service.validate(db, article_id)
    return DecisionTreeValidationResult(
        is_valid=not issues,
        issues=[DecisionTreeIssue(node_id=i.node_id, problem=i.problem) for i in issues],
    )


@router.patch(
    "/decision-tree-nodes/{nodeId}",
    operation_id="updateDecisionTreeNode",
    **rbac(UserRole.ADMIN),
)
def update_decision_tree_node(
    node_id: NodeId, body: DecisionTreeNodeCreateRequest, db: DbDep
) -> DecisionTreeNodeOut:
    return DecisionTreeNodeOut.model_validate(service.update_node(db, node_id, _node_input(body)))


@router.delete(
    "/decision-tree-nodes/{nodeId}",
    operation_id="deleteDecisionTreeNode",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    **rbac(UserRole.ADMIN),
)
def delete_decision_tree_node(node_id: NodeId, db: DbDep) -> Response:
    service.delete_node(db, node_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
