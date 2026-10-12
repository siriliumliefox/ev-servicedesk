"""Гонки Knowledge Base Service (Глава 14, ADR 0018 п. 7, 11): отдельные соединения и COMMIT.

- Правки опубликованной статьи идут по очереди (блокировка строки статьи): номера версий
  уникальны и идут подряд, без 500 от uq_knowledge_article_revision_article_id_version.
- Одновременные корни: создаётся ровно один, остальные — 409 (а не 500 от частичного UNIQUE).
- Узел во время публикации: либо попадает в дерево и снимок, либо 409 ARTICLE_PUBLISHED —
  живое дерево опубликованной статьи совпадает со снимком её версии.
- Эскалация держит узел FOR KEY SHARE: удаление узла ждёт создания тикета.
"""

from collections.abc import Iterator

import pytest
from sqlalchemy import Engine, delete, select, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.core.errors import ApiError
from app.domain.knowledge import service
from app.domain.knowledge.service import NodeInput
from app.models import DecisionTreeNode, KnowledgeArticle, KnowledgeArticleRevision
from tests.api.knowledge_support import build_tree
from tests.api.test_concurrency import storm

THREADS = 8


@pytest.fixture
def articles(migrated_engine: Engine) -> Iterator[list[int]]:
    """id статей теста; после теста удаляются (узлы и версии — каскадом)."""
    created: list[int] = []
    yield created
    with Session(migrated_engine) as cleanup:
        cleanup.execute(delete(KnowledgeArticle).where(KnowledgeArticle.id.in_(created)))
        cleanup.commit()


def session(engine: Engine) -> Session:
    return Session(engine, expire_on_commit=False)


def test_parallel_edits_number_versions_in_order(migrated_engine: Engine, articles: list[int]):
    with session(migrated_engine) as s:
        tree = build_tree(s, "Гонка версий")
    articles.append(tree.article.id)
    turn = iter(range(100))

    def edit() -> object:
        title = f"Редакция {next(turn)}"
        with session(migrated_engine) as s:
            return service.update_article(s, tree.article.id, {"title": title}).version

    results = storm(THREADS, edit)
    assert sorted(results) == list(range(2, THREADS + 2)), results
    with session(migrated_engine) as check:
        versions = check.scalars(
            select(KnowledgeArticleRevision.version)
            .where(KnowledgeArticleRevision.article_id == tree.article.id)
            .order_by(KnowledgeArticleRevision.version)
        ).all()
        article = check.get_one(KnowledgeArticle, tree.article.id)
        last = check.scalars(
            select(KnowledgeArticleRevision).where(
                KnowledgeArticleRevision.article_id == tree.article.id,
                KnowledgeArticleRevision.version == THREADS + 1,
            )
        ).one()
    assert versions == list(range(1, THREADS + 2))
    assert (article.version, article.title) == (THREADS + 1, last.title), "последняя — текущая"


def test_parallel_roots_create_exactly_one(migrated_engine: Engine, articles: list[int]):
    with session(migrated_engine) as s:
        tree = build_tree(s, "Гонка корней", publish=False)
        s.execute(
            text("UPDATE decision_tree_node SET is_root = false WHERE id = :id"),
            {"id": tree.root.id},
        )
        s.commit()
    articles.append(tree.article.id)

    def add_root() -> object:
        with session(migrated_engine) as s:
            node = NodeInput("Корень?", (("Нет", tree.escalation.id),), True, False)
            return service.create_node(s, tree.article.id, node)

    results = storm(THREADS, add_root)
    created = [r for r in results if isinstance(r, DecisionTreeNode)]
    conflicts = [r for r in results if isinstance(r, ApiError)]
    assert len(created) == 1, results
    assert len(conflicts) == THREADS - 1
    assert {c.code for c in conflicts} == {"DECISION_TREE_ROOT_EXISTS"}


def test_node_edit_during_publication(migrated_engine: Engine, articles: list[int]):
    """Публикация и правка узла одновременно — снимок версии совпадает с живым деревом."""
    for attempt in range(5):
        with session(migrated_engine) as s:
            tree = build_tree(s, f"Гонка публикации {attempt}", publish=False)
        articles.append(tree.article.id)
        jobs = iter(["publish", "edit"])

        def act() -> object:
            job = next(jobs)
            with session(migrated_engine) as s:
                if job == "publish":
                    return service.update_article(s, tree.article.id, {"is_published": True})
                node = NodeInput(
                    "Перезагрузили? (уточнено)",
                    (("Помогло", tree.solved.id), ("Не помогло", tree.escalation.id)),
                    True,
                    False,
                )
                return service.update_node(s, tree.root.id, node)

        results = storm(2, act)
        errors = [r for r in results if isinstance(r, Exception)]
        assert all(
            isinstance(e, ApiError) and e.code == "ARTICLE_PUBLISHED" for e in errors
        ), results
        with session(migrated_engine) as check:
            live = check.scalars(
                select(DecisionTreeNode)
                .where(DecisionTreeNode.article_id == tree.article.id)
                .order_by(DecisionTreeNode.id)
            ).all()
            snapshot = check.scalars(
                select(KnowledgeArticleRevision).where(
                    KnowledgeArticleRevision.article_id == tree.article.id
                )
            ).one()
        assert [(n.id, n.question_text, n.options) for n in live] == [
            (n["id"], n["question_text"], n["options"]) for n in snapshot.decision_tree
        ]


@pytest.mark.parametrize("change", ["delete", "demote"])
def test_escalation_blocks_node_change(migrated_engine: Engine, articles: list[int], change):
    """Узел под эскалацией (FOR SHARE): удаление и смена типа ждут COMMIT тикета (п. 11)."""
    with session(migrated_engine) as s:
        tree = build_tree(s, f"Гонка эскалации {change}")
        # Снять с публикации, чтобы дерево можно было править.
        service.unpublish_article(s, tree.article.id)
        if change == "delete":  # на узел эскалации не должны ссылаться другие узлы
            service.update_node(
                s, tree.root.id, NodeInput("Перезагрузили?", (("Да", tree.solved.id),), True, False)
            )
    articles.append(tree.article.id)

    with session(migrated_engine) as escalating, session(migrated_engine) as admin:
        assert service.escalation_version(escalating, tree.article.id, tree.escalation.id) == 1
        admin.execute(text("SET lock_timeout = '300ms'"))
        with pytest.raises(OperationalError, match="lock"):
            if change == "delete":
                service.delete_node(admin, tree.escalation.id)
            else:
                service.update_node(
                    admin, tree.escalation.id, NodeInput("Решено", (), False, False)
                )
        admin.rollback()
        escalating.commit()
        admin.execute(text("SET lock_timeout = 0"))
        # После COMMIT эскалации правка проходит.
        if change == "delete":
            service.delete_node(admin, tree.escalation.id)
        else:
            node = service.update_node(
                admin, tree.escalation.id, NodeInput("Решено", (), False, False)
            )
            assert node.is_escalation is False
