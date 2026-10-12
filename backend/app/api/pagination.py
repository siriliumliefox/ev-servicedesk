"""Пагинация коллекций: параметры page/page_size и PaginationMeta контракта (ADR 0007)."""

from dataclasses import dataclass
from typing import Annotated, Any

from fastapi import Depends, Query
from pydantic import BaseModel
from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session

from app.core.db import BIGINT_MAX

PAGE_SIZE_MAX = 100
# OFFSET = (page - 1) * page_size — BIGINT в PostgreSQL: больше — ошибка БД и 500, а не 422.
PAGE_MAX = BIGINT_MAX // PAGE_SIZE_MAX + 1


class PaginationMeta(BaseModel):
    page: int
    page_size: int
    total_items: int
    total_pages: int


@dataclass(frozen=True)
class Page:
    page: int
    page_size: int


def page_params(
    page: Annotated[int, Query(ge=1, le=PAGE_MAX)] = 1,
    page_size: Annotated[int, Query(ge=1, le=PAGE_SIZE_MAX)] = 20,
) -> Page:
    return Page(page=page, page_size=page_size)


PageDep = Annotated[Page, Depends(page_params)]


def paginate(db: Session, stmt: Select[Any], page: Page) -> tuple[list[Any], PaginationMeta]:
    """Одна страница `stmt` (порядок задаёт вызывающий) и метаданные по полному числу строк."""
    rows, meta = paginate_rows(db, stmt, page)
    return [row[0] for row in rows], meta


def paginate_rows(db: Session, stmt: Select[Any], page: Page) -> tuple[list[Any], PaginationMeta]:
    """Как `paginate`, но строки целиком — для запросов из нескольких колонок."""
    total = db.scalar(select(func.count()).select_from(stmt.order_by(None).subquery())) or 0
    items = list(db.execute(stmt.limit(page.page_size).offset((page.page - 1) * page.page_size)))
    meta = PaginationMeta(
        page=page.page,
        page_size=page.page_size,
        total_items=total,
        total_pages=-(-total // page.page_size),
    )
    return items, meta
