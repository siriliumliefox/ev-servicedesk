"""Видимость статей базы знаний (RBAC-05, ADR 0018 п. 8).

Клиент и инженер видят только опубликованные статьи; черновик для них не существует (404),
как и его дерево и история версий. Администратор видит все. Правка — только admin (RBAC
маршрута); операции правки блокируют строку статьи (`for_change`, п. 7).
"""

from sqlalchemy import ColumnElement, select, true
from sqlalchemy.orm import Session

from app.core.db import is_db_id
from app.core.errors import ApiError
from app.models import AppUser, KnowledgeArticle
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
