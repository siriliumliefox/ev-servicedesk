"""Проверки чек-листа главы 14 (ADR 0018) на реальных токенах Auth и PostgreSQL.

- «Интеграционный тест: дерево решений → эскалация → тикет с пометкой» — админ строит и
  публикует дерево через API, клиент проходит его от корня по вариантам до эскалации и создаёт
  тикет, инженер видит в карточке статью и её версию.
- «Проверка отсутствия тупиков в дереве решений» — сценарии миграции 0011 (DoD: ≥5 реальных
  сценариев ошибок) проходят проверку API и обход всех путей клиента.
"""

import pytest
from fastapi.testclient import TestClient

from app.models.enums import TicketCategory, UserRole
from tests.api.conftest import Headers, add_vehicle
from tests.api.knowledge_support import api, api_tree, update_article
from tests.api.ticket_support import create

ADMIN_PHONE = "+375293600001"
ENGINEER_PHONE = "+375293600002"
CLIENT_PHONE = "+375293600003"


@pytest.fixture
def admin(as_staff) -> Headers:
    return as_staff(ADMIN_PHONE, UserRole.ADMIN)[0]


@pytest.fixture
def engineer(as_staff) -> Headers:
    return as_staff(ENGINEER_PHONE)[0]


@pytest.fixture
def owner(as_client) -> Headers:
    return as_client(CLIENT_PHONE)


def tree_of(client: TestClient, headers: Headers, article_id: int) -> dict[int, dict]:
    body = api(
        client,
        "GET",
        f"/knowledge-articles/{article_id}/decision-tree",
        headers,
        "listDecisionTreeNodes",
        200,
        params={"page_size": 100},
    )
    assert body["meta"]["total_items"] == len(body["items"]), "всё дерево — на одной странице"
    return {n["id"]: n for n in body["items"]}


def walk(nodes: dict[int, dict], answers: list[str]) -> tuple[list[dict], list[str]]:
    """Клиент проходит дерево от корня, выбирая варианты по меткам."""
    path = [next(n for n in nodes.values() if n["is_root"])]
    for label in answers:
        option = next(o for o in path[-1]["options"] if o["label"] == label)
        path.append(nodes[option["next_node_id"]])
    return path, answers


def card(client: TestClient, headers: Headers, ticket_id: int) -> dict:
    return api(client, "GET", f"/tickets/{ticket_id}", headers, "getTicket", 200)


def test_decision_tree_escalation_creates_marked_ticket(client, admin, engineer, owner):
    vehicle = add_vehicle(client, owner)
    built = api_tree(client, admin, title="Нет звука в колонках", category="audio")
    article_id = built["article"]["id"]
    update_article(client, admin, article_id, is_published=True)

    # Клиент: раздел «Устранение неполадок» → статья категории → дерево → эскалация.
    found = api(
        client,
        "GET",
        "/knowledge-articles",
        owner,
        "listKnowledgeArticles",
        200,
        params={"article_type": "troubleshooting", "category": "audio", "search": "звук"},
    )
    article = next(a for a in found["items"] if a["id"] == article_id)
    path, answers = walk(tree_of(client, owner, article_id), ["Не помогло"])
    final = path[-1]
    assert final["is_escalation"] and final["id"] == built["escalation"]["id"]
    steps = "\n".join(f"— {n['question_text']} → {a}" for n, a in zip(path, answers, strict=False))
    ticket = create(
        client,
        owner,
        vehicle["id"],
        category=article["category"],
        description=f"{article['title']}. Что уже пробовал:\n{steps}",
        source_article_id=article_id,
        source_node_id=final["id"],
    )
    mark = {"id": article_id, "title": "Нет звука в колонках", "version": 1}
    assert ticket["source_article"] == mark
    assert ticket["category"] == "audio" and ticket["status"] == "new"

    # Инженер: тикет в очереди, в карточке — пометка «из базы знаний» и ход диагностики.
    queue = api(client, "GET", "/tickets", engineer, "listTickets", 200, params={"status": "new"})
    assert ticket["id"] in [t["id"] for t in queue["items"]]
    seen = card(client, engineer, ticket["id"])
    assert seen["source_article"] == mark
    assert "Перезагрузили мультимедиа? → Не помогло" in seen["description"]

    # Новая версия статьи: старый тикет помнит версию, которую видел клиент.
    update_article(client, admin, article_id, title="Нет звука в динамиках")
    assert card(client, engineer, ticket["id"])["source_article"] == mark
    second = create(
        client, owner, vehicle["id"], source_article_id=article_id, source_node_id=final["id"]
    )
    assert second["source_article"] == {
        "id": article_id,
        "title": "Нет звука в динамиках",
        "version": 2,
    }

    # Статью сняли, пока клиент проходил дерево: эскалация всё равно создаёт тикет (п. 11).
    api(
        client,
        "DELETE",
        f"/knowledge-articles/{article_id}",
        admin,
        "unpublishKnowledgeArticle",
        204,
    )
    late = create(
        client, owner, vehicle["id"], source_article_id=article_id, source_node_id=final["id"]
    )
    assert late["source_article"]["version"] == 2


def test_seeded_scenarios_cover_every_category_without_dead_ends(client, admin, owner):
    """DoD: ≥5 реальных сценариев ошибок; проверка отсутствия тупиков — по каждому."""
    listing = api(
        client,
        "GET",
        "/knowledge-articles",
        owner,
        "listKnowledgeArticles",
        200,
        params={"article_type": "troubleshooting", "page_size": 100},
    )
    seeded = [a for a in listing["items"] if a["version"] == 1 and a["is_published"]]
    assert len(seeded) >= 5
    assert {a["category"] for a in seeded} == {c.value for c in TicketCategory}

    for article in seeded:
        result = api(
            client,
            "GET",
            f"/knowledge-articles/{article['id']}/decision-tree/validate",
            admin,
            "validateDecisionTree",
            200,
        )
        assert result == {"is_valid": True, "issues": []}, article["title"]
        nodes = tree_of(client, owner, article["id"])
        assert 4 <= len(nodes) <= 8, article["title"]
        assert article["content"].strip(), "у сценария есть вводный текст"

        # Все пути клиента от корня: каждый заканчивается решением или эскалацией, без циклов.
        finals: list[dict] = []
        root = next(n for n in nodes.values() if n["is_root"])
        stack: list[tuple[dict, frozenset[int]]] = [(root, frozenset({root["id"]}))]
        while stack:
            node, seen = stack.pop()
            if node["is_escalation"] or not node["options"]:
                finals.append(node)
                continue
            for option in node["options"]:
                target = nodes[option["next_node_id"]]
                assert target["id"] not in seen, f"цикл в «{article['title']}»"
                stack.append((target, seen | {target["id"]}))
        assert any(n["is_escalation"] for n in finals), article["title"]
        assert any(not n["is_escalation"] for n in finals), "есть путь «проблема решена»"
        assert {n["id"] for n in finals} == {
            n["id"] for n in nodes.values() if n["is_escalation"] or not n["options"]
        }, "каждый финал достижим"
