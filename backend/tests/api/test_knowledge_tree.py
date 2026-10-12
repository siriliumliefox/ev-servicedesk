"""Дерево решений через API (Глава 14, ADR 0018 п. 3–6): узлы, корень, публикация, проверка.

Чистая проверка тупиков — tests/domain/test_decision_tree.py; здесь — правила сервиса и
ответы контракта.
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models import DecisionTreeNode, Ticket
from app.models.enums import UserRole
from tests.api.conftest import API, Headers, add_vehicle
from tests.api.knowledge_support import api, api_tree, create_article, create_node, update_article
from tests.api.ticket_support import create, error_code

ADMIN_PHONE = "+375293500001"
CLIENT_PHONE = "+375293500002"


@pytest.fixture
def admin(as_staff) -> Headers:
    return as_staff(ADMIN_PHONE, UserRole.ADMIN)[0]


def node_body(question: str = "Вопрос", options=(), *, root=False, escalation=False) -> dict:
    return {
        "question_text": question,
        "options": [{"label": label, "next_node_id": target} for label, target in options],
        "is_root": root,
        "is_escalation": escalation,
    }


def post_node(client: TestClient, admin: Headers, article_id: int, body: dict):
    r = client.post(
        f"{API}/knowledge-articles/{article_id}/decision-tree", json=body, headers=admin
    )
    return r


def patch_node(client: TestClient, admin: Headers, node_id: int, body: dict):
    r = client.patch(f"{API}/decision-tree-nodes/{node_id}", json=body, headers=admin)
    return r


def validate(client: TestClient, admin: Headers, article_id: int) -> dict:
    return api(
        client,
        "GET",
        f"/knowledge-articles/{article_id}/decision-tree/validate",
        admin,
        "validateDecisionTree",
        200,
    )


def problems(result: dict) -> set[tuple[str, int | None]]:
    return {(i["problem"], i.get("node_id")) for i in result["issues"]}


# ---------- Узлы ----------


def test_nodes_listed_in_creation_order(client, admin):
    tree = api_tree(client, admin)
    body = api(
        client,
        "GET",
        f"/knowledge-articles/{tree['article']['id']}/decision-tree",
        admin,
        "listDecisionTreeNodes",
        200,
    )
    assert [n["id"] for n in body["items"]] == [
        tree["solved"]["id"],
        tree["escalation"]["id"],
        tree["root"]["id"],
    ]
    root = body["items"][2]
    assert root["options"] == [
        {"label": "Помогло", "next_node_id": tree["solved"]["id"]},
        {"label": "Не помогло", "next_node_id": tree["escalation"]["id"]},
    ]
    assert (root["is_root"], root["is_escalation"], root["article_id"]) == (
        True,
        False,
        tree["article"]["id"],
    )


def test_single_root(client, admin):
    tree = api_tree(client, admin)
    article_id, root = tree["article"]["id"], tree["root"]
    r = post_node(client, admin, article_id, node_body(root=True))
    assert (r.status_code, error_code(r)) == (409, "DECISION_TREE_ROOT_EXISTS")
    r = patch_node(client, admin, tree["solved"]["id"], node_body("Решено", root=True))
    assert (r.status_code, error_code(r)) == (409, "DECISION_TREE_ROOT_EXISTS")
    # Сам корень сохраняет признак; сменить корень — снять признак, затем поставить другому.
    keep = node_body("Перезагрузили?", [("Не помогло", tree["escalation"]["id"])], root=True)
    assert patch_node(client, admin, root["id"], keep).status_code == 200
    assert patch_node(client, admin, root["id"], keep | {"is_root": False}).status_code == 200
    assert patch_node(client, admin, tree["solved"]["id"], node_body(root=True)).status_code == 200


def test_next_node_must_be_in_same_article(client, admin):
    tree = api_tree(client, admin)
    other = api_tree(client, admin, title="Другая")
    article_id = tree["article"]["id"]
    for target in (other["solved"]["id"], 10**9):
        r = post_node(client, admin, article_id, node_body(options=[("Дальше", target)]))
        assert (r.status_code, error_code(r)) == (422, "INVALID_NEXT_NODE"), target
        assert r.json()["error"]["details"]["fields"][0]["loc"] == [
            "body",
            "options",
            0,
            "next_node_id",
        ]
    # Ссылка на себя («повторите шаг») допустима; тупик ловит проверка дерева.
    solved = tree["solved"]
    r = patch_node(client, admin, solved["id"], node_body("Ещё раз?", [("Снова", solved["id"])]))
    assert r.status_code == 200


@pytest.mark.parametrize(
    "body",
    [
        node_body("   "),
        node_body("я" * 1001),
        node_body("NUL\x00"),
        node_body(options=[("", 1)]),
        node_body(options=[("я" * 101, 1)]),
        node_body(options=[("Строка\nвторая", 1)]),
        node_body(options=[("CSI\x9b", 1)]),
        node_body(options=[("Да", 1), ("Да", 1)]),  # метки узла не повторяются
        node_body(options=[(f"Вариант {i}", 1) for i in range(11)]),
        node_body(options=[("Да", 2**63)]),
        node_body() | {"options": [{"label": "Да", "next_node_id": None}]},  # null — 422
        node_body() | {"options": [{"label": "Да"}]},
        {"question_text": "Без признаков"},
    ],
)
def test_node_validation(client, admin, body):
    article = create_article(client, admin)
    r = post_node(client, admin, article["id"], body)
    assert (r.status_code, error_code(r)) == (422, "VALIDATION_ERROR"), r.text


def test_node_limits_are_inclusive(client, admin):
    article = create_article(client, admin)
    target = create_node(client, admin, article["id"], "я" * 1000)
    body = node_body(" Вопрос ", [(f"{i:03d}" + "я" * 97, target["id"]) for i in range(10)])
    created = post_node(client, admin, article["id"], body)
    assert created.status_code == 201
    assert created.json()["question_text"] == "Вопрос"
    assert len(created.json()["options"]) == 10


def test_tree_size_limit(client, admin, db: Session):
    article = create_article(client, admin)
    db.add_all(
        DecisionTreeNode(article_id=article["id"], question_text=f"Узел {i}") for i in range(99)
    )
    db.commit()
    assert post_node(client, admin, article["id"], node_body()).status_code == 201  # 100-й
    r = post_node(client, admin, article["id"], node_body())
    assert (r.status_code, error_code(r)) == (422, "DECISION_TREE_TOO_LARGE")


def test_delete_node(client, admin):
    tree = api_tree(client, admin)
    r = client.delete(f"{API}/decision-tree-nodes/{tree['solved']['id']}", headers=admin)
    assert (r.status_code, error_code(r)) == (409, "DECISION_TREE_NODE_REFERENCED")
    assert r.json()["error"]["details"]["referenced_by"] == [tree["root"]["id"]]
    # Корень без входящих ссылок удаляется; после него — листья.
    for key in ("root", "solved", "escalation"):
        api(
            client,
            "DELETE",
            f"/decision-tree-nodes/{tree[key]['id']}",
            admin,
            "deleteDecisionTreeNode",
            204,
        )
    for node_id in (tree["root"]["id"], 10**9, 2**63):
        api(
            client,
            "DELETE",
            f"/decision-tree-nodes/{node_id}",
            admin,
            "deleteDecisionTreeNode",
            404,
        )
        r = patch_node(client, admin, node_id, node_body())
        assert r.status_code == 404


def test_self_reference_does_not_block_delete(client, admin):
    article = create_article(client, admin)
    node = create_node(client, admin, article["id"], "Повторить?")
    patch_node(client, admin, node["id"], node_body("Повторить?", [("Снова", node["id"])]))
    api(
        client, "DELETE", f"/decision-tree-nodes/{node['id']}", admin, "deleteDecisionTreeNode", 204
    )


def test_missing_article_for_tree(client, admin):
    for article_id in (10**9, 2**63):
        r = post_node(client, admin, article_id, node_body())
        assert r.status_code == 404
        api(
            client,
            "GET",
            f"/knowledge-articles/{article_id}/decision-tree/validate",
            admin,
            "validateDecisionTree",
            404,
        )
        api(
            client,
            "GET",
            f"/knowledge-articles/{article_id}/decision-tree",
            admin,
            "listDecisionTreeNodes",
            404,
        )


# ---------- Тип статьи и публикация (п. 5) ----------


def test_guide_has_no_tree(client, admin):
    article = create_article(client, admin, article_type="guide", category=None)
    r = post_node(client, admin, article["id"], node_body(root=True, escalation=True))
    assert (r.status_code, error_code(r)) == (409, "ARTICLE_TYPE_HAS_NO_TREE")
    assert validate(client, admin, article["id"]) == {"is_valid": True, "issues": []}


def test_published_tree_is_read_only(client, admin):
    tree = api_tree(client, admin)
    update_article(client, admin, tree["article"]["id"], is_published=True)
    calls = [
        post_node(client, admin, tree["article"]["id"], node_body()),
        patch_node(client, admin, tree["solved"]["id"], node_body("Решено")),
        client.delete(f"{API}/decision-tree-nodes/{tree['solved']['id']}", headers=admin),
    ]
    for r in calls:
        assert (r.status_code, error_code(r)) == (409, "ARTICLE_PUBLISHED"), r.request.method


def test_publication_requires_valid_tree(client, admin):
    article = create_article(client, admin, title="Пустое дерево")
    article_id = article["id"]

    def publish_issues() -> set:
        r = client.patch(
            f"{API}/knowledge-articles/{article_id}", json={"is_published": True}, headers=admin
        )
        assert (r.status_code, error_code(r)) == (409, "DECISION_TREE_INVALID")
        return {(i["problem"], i.get("node_id")) for i in r.json()["error"]["details"]["issues"]}

    assert publish_issues() == {("NO_ROOT", None)}
    solved = create_node(client, admin, article_id, "Решено")
    root = create_node(client, admin, article_id, "Помогло?", [("Да", solved["id"])], root=True)
    assert publish_issues() == {("NO_ESCALATION", None)}
    assert problems(validate(client, admin, article_id)) == {("NO_ESCALATION", None)}

    loop = create_node(client, admin, article_id, "Цикл")
    patch_node(client, admin, loop["id"], node_body("Цикл", [("Снова", loop["id"])]))
    escalation = create_node(client, admin, article_id, "Обращение", escalation=True)
    patch_node(
        client,
        admin,
        root["id"],
        node_body("Помогло?", [("Да", solved["id"]), ("Нет", loop["id"])], root=True),
    )
    assert publish_issues() == {
        ("DEAD_END", loop["id"]),
        ("UNREACHABLE", escalation["id"]),
        ("NO_ESCALATION", None),  # эскалация есть, но недостижима
    }
    # Ничего не опубликовано и версий нет.
    assert (
        api(client, "GET", f"/knowledge-articles/{article_id}", admin, "getKnowledgeArticle", 200)[
            "is_published"
        ]
        is False
    )

    patch_node(
        client,
        admin,
        loop["id"],
        node_body("Цикл", [("Снова", loop["id"]), ("Сдаюсь", escalation["id"])]),
    )
    assert validate(client, admin, article_id) == {"is_valid": True, "issues": []}
    published = update_article(client, admin, article_id, is_published=True)
    assert (published["is_published"], published["version"]) == (True, 1)


# ---------- Удаление узла и тикеты ----------


def test_deleted_escalation_node_keeps_ticket_mark(client, admin, as_client, db: Session):
    """Ссылка тикета на удалённый узел обнуляется, версия статьи («пометка») остаётся."""
    owner = as_client(CLIENT_PHONE)
    vehicle = add_vehicle(client, owner)
    tree = api_tree(client, admin)
    article_id = tree["article"]["id"]
    update_article(client, admin, article_id, is_published=True)
    ticket = create(
        client,
        owner,
        vehicle["id"],
        source_article_id=article_id,
        source_node_id=tree["escalation"]["id"],
    )

    api(
        client,
        "DELETE",
        f"/knowledge-articles/{article_id}",
        admin,
        "unpublishKnowledgeArticle",
        204,
    )
    patch_node(
        client,
        admin,
        tree["root"]["id"],
        node_body("Перезагрузили?", [("Помогло", tree["solved"]["id"])], root=True),
    )
    api(
        client,
        "DELETE",
        f"/decision-tree-nodes/{tree['escalation']['id']}",
        admin,
        "deleteDecisionTreeNode",
        204,
    )

    row = db.get(Ticket, ticket["id"], populate_existing=True)
    assert (row.source_article_id, row.source_node_id, row.source_article_version) == (
        article_id,
        None,
        1,
    )
    # Узел удалён — эскалация с ним невозможна (клиент повторяет без узла).
    r = client.post(
        f"{API}/tickets",
        json={
            "vehicle_id": vehicle["id"],
            "category": "audio",
            "description": "x",
            "source_article_id": article_id,
            "source_node_id": tree["escalation"]["id"],
        },
        headers=owner,
    )
    assert (r.status_code, error_code(r)) == (422, "INVALID_SOURCE_REFERENCE")
