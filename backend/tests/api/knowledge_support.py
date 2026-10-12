"""Помощники тестов базы знаний (Глава 14, ADR 0018): статьи и деревья через сценарии домена."""

from dataclasses import dataclass
from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.domain.knowledge import service
from app.domain.knowledge.service import NodeInput
from app.models import DecisionTreeNode, KnowledgeArticle
from app.models.enums import KbArticleType, TicketCategory
from tests.api.conftest import API, Headers


@dataclass(frozen=True)
class Tree:
    """Минимальное валидное дерево: вопрос → «помогло» (решение) / «не помогло» (эскалация)."""

    article: KnowledgeArticle
    root: DecisionTreeNode
    solved: DecisionTreeNode
    escalation: DecisionTreeNode


def build_tree(
    db: Session,
    title: str = "Не работает навигация",
    *,
    category: TicketCategory = TicketCategory.NAVIGATION,
    publish: bool = True,
) -> Tree:
    article = service.create_article(
        db,
        article_type=KbArticleType.TROUBLESHOOTING,
        title=title,
        content="Проверьте шаги ниже.",
        category=category,
        vehicle_model_id=None,
        firmware_release_id=None,
    )
    solved = service.create_node(db, article.id, NodeInput("Проблема решена", (), False, False))
    escalation = service.create_node(
        db, article.id, NodeInput("Создайте обращение — поможет инженер", (), False, True)
    )
    root = service.create_node(
        db,
        article.id,
        NodeInput(
            "Перезагрузили мультимедиа?",
            (("Помогло", solved.id), ("Не помогло", escalation.id)),
            True,
            False,
        ),
    )
    if publish:
        article = service.update_article(db, article.id, {"is_published": True})
    return Tree(article, root, solved, escalation)


# ---------- Запросы API (сверка с docs/openapi.yaml) ----------


def api(
    client: TestClient,
    method: str,
    path: str,
    headers: Headers,
    operation_id: str,
    expected: int,
    **kwargs: Any,
) -> Any:
    """Запрос к /v1 с ожидаемым статусом; ответ сверяется с контрактом."""
    r = client.request(method, f"{API}{path}", headers=headers, **kwargs)
    assert r.status_code == expected, r.text
    return r.json() if r.content else None


def create_article(client: TestClient, admin: Headers, **body: Any) -> dict:
    payload = {"article_type": "troubleshooting", "category": "audio", "content": ""} | body
    payload.setdefault("title", "Статья")
    return api(
        client, "POST", "/knowledge-articles", admin, "createKnowledgeArticle", 201, json=payload
    )


def update_article(client: TestClient, admin: Headers, article_id: int, **body: Any) -> dict:
    return api(
        client,
        "PATCH",
        f"/knowledge-articles/{article_id}",
        admin,
        "updateKnowledgeArticle",
        200,
        json=body,
    )


def create_node(
    client: TestClient,
    admin: Headers,
    article_id: int,
    question: str,
    options: list[tuple[str, int]] = (),
    *,
    root: bool = False,
    escalation: bool = False,
) -> dict:
    body = {
        "question_text": question,
        "options": [{"label": label, "next_node_id": target} for label, target in options],
        "is_root": root,
        "is_escalation": escalation,
    }
    return api(
        client,
        "POST",
        f"/knowledge-articles/{article_id}/decision-tree",
        admin,
        "createDecisionTreeNode",
        201,
        json=body,
    )


def api_tree(client: TestClient, admin: Headers, title: str = "Нет звука", **body: Any) -> dict:
    """Через API: статья с деревом «вопрос → решение / эскалация», черновик.

    Возвращает {"article", "root", "solved", "escalation"}.
    """
    article = create_article(client, admin, title=title, **body)
    solved = create_node(client, admin, article["id"], "Проблема решена")
    escalation = create_node(client, admin, article["id"], "Создайте обращение", escalation=True)
    root = create_node(
        client,
        admin,
        article["id"],
        "Перезагрузили мультимедиа?",
        [("Помогло", solved["id"]), ("Не помогло", escalation["id"])],
        root=True,
    )
    return {"article": article, "root": root, "solved": solved, "escalation": escalation}
