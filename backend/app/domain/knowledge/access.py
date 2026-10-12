"""Видимость статей базы знаний (RBAC-05, ADR 0018 п. 8).

Клиент и инженер видят только опубликованные статьи; черновик для них не существует (404),
как и его дерево. История версий открыта персоналу у статьи с хотя бы одной опубликованной
версией, даже снятой с публикации (`get_with_history`): на неё может ссылаться тикет
(эскалация, п. 11). Администратор видит все. Правка — только admin (RBAC маршрута);
операции правки блокируют строку статьи (`for_change`, п. 7).
"""

from sqlalchemy import ColumnElement, exists, or_, select, true
from sqlalchemy.orm import Session

from app.core.db import is_db_id
from app.core.errors import ApiError
from app.models import AppUser, KnowledgeArticle, KnowledgeArticleRevision
from app.models.enums import UserRole


def not_found() -> ApiError:
    return ApiError(404, "NOT_FOUND", "Статья не найдена")


def visible(user: AppUser) -> ColumnElement[bool]:
    if user.role is UserRole.ADMIN:
        return true()
    return KnowledgeArticle.is_published.is_(True)


def get_article(db: Session, user: AppUser, article_id: int) -> KnowledgeArticle:
    """Статья, видимая `user`, иначе 404."""
    if not is_db_id(article_id):
        raise not_found()
    article = db.scalars(
        select(KnowledgeArticle).where(KnowledgeArticle.id == article_id, visible(user))
    ).one_or_none()
    if article is None:
        raise not_found()
    return article


def get_with_history(db: Session, user: AppUser, article_id: int) -> KnowledgeArticle:
    """Статья для истории версий: видимая `user` или с опубликованной версией, иначе 404.

    Черновое содержание не раскрывается: версии — то, что уже видели клиенты.
    """
    if not is_db_id(article_id):
        raise not_found()
    published_once = exists().where(KnowledgeArticleRevision.article_id == KnowledgeArticle.id)
    article = db.scalars(
        select(KnowledgeArticle).where(
            KnowledgeArticle.id == article_id, or_(visible(user), published_once)
        )
    ).one_or_none()
    if article is None:
        raise not_found()
    return article


def for_change(db: Session, article_id: int) -> KnowledgeArticle:
    """Статья под блокировкой FOR NO KEY UPDATE: правки статьи и её дерева идут по очереди.

    Блокировка не мешает FK-проверкам (тикеты, узлы, версии ссылаются на статью).
    """
    if not is_db_id(article_id):
        raise not_found()
    article = db.scalars(
        select(KnowledgeArticle)
        .where(KnowledgeArticle.id == article_id)
        .with_for_update(key_share=True)
        .execution_options(populate_existing=True)
    ).one_or_none()
    if article is None:
        raise not_found()
    return article
