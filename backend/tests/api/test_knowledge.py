"""Knowledge Base Service (Глава 14, ADR 0018): статьи, доступ RBAC-05, версии, поиск, фильтры.

Токены — настоящие (Глава 10). Дерево решений и его проверка — test_knowledge_tree.py,
сценарии чек-листа (эскалация, тупики, ≥5 сценариев) — test_knowledge_checklist.py.
Миграция 0011 уже добавила 5 опубликованных статей — списки сверяются по своим id.
"""

import unicodedata
from datetime import UTC, date, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.models import FirmwareRelease, KnowledgeArticle, KnowledgeArticleRevision, VehicleModel
from app.models.enums import KbArticleType, UserRole
from tests.api.conftest import API, Headers, model_id
from tests.api.knowledge_support import (
    api,
    api_tree,
    create_article,
    create_node,
    update_article,
)
from tests.api.ticket_support import error_code

ADMIN_PHONE = "+375293400001"
ENGINEER_PHONE = "+375293400002"
CLIENT_PHONE = "+375293400003"


@pytest.fixture
def admin(as_staff) -> Headers:
    return as_staff(ADMIN_PHONE, UserRole.ADMIN)[0]


@pytest.fixture
def engineer(as_staff) -> Headers:
    return as_staff(ENGINEER_PHONE)[0]


@pytest.fixture
def owner(as_client) -> Headers:
    return as_client(CLIENT_PHONE)


def ids(client: TestClient, headers: Headers, **params) -> list[int]:
    r = client.get(
        f"{API}/knowledge-articles", params={"page_size": 100, **params}, headers=headers
    )
    assert r.status_code == 200, r.text
    return [a["id"] for a in r.json()["items"]]


def publish(client: TestClient, admin: Headers, article_id: int) -> dict:
    return update_article(client, admin, article_id, is_published=True)


def guide(client: TestClient, admin: Headers, title: str = "Как обновить карты", **body) -> dict:
    return create_article(client, admin, article_type="guide", category=None, title=title, **body)


# ---------- Создание и правка ----------


def test_create_draft(client, admin):
    article = create_article(
        client, admin, title="  Нет звука  ", content="## Шаги\n\n    код\n", category="audio"
    )
    assert article["title"] == "Нет звука"
    assert article["content"] == "## Шаги\n\n    код\n", "Markdown хранится как есть"
    assert (article["version"], article["is_published"]) == (1, False)
    assert article["category"] == "audio" and article["updated_at"]
    assert guide(client, admin)["category"] is None


@pytest.mark.parametrize(
    ("body", "code"),
    [
        ({"category": None}, "CATEGORY_REQUIRED"),  # troubleshooting без категории
        ({"title": "   "}, "VALIDATION_ERROR"),
        ({"title": "я" * 201}, "VALIDATION_ERROR"),
        ({"title": "Строка\nвторая"}, "VALIDATION_ERROR"),
        ({"title": "CSI\x9bзаголовок"}, "VALIDATION_ERROR"),  # C1 — как в тексте
        ({"content": "x" * 50_001}, "VALIDATION_ERROR"),
        ({"content": "NUL\x00"}, "VALIDATION_ERROR"),
        ({"content": "CSI\x9b"}, "VALIDATION_ERROR"),
        ({"vehicle_model_id": 10**9}, "VEHICLE_MODEL_NOT_FOUND"),
        ({"vehicle_model_id": 2**63}, "VALIDATION_ERROR"),
        ({"firmware_release_id": 10**9}, "FIRMWARE_RELEASE_NOT_FOUND"),
        ({"category": "weather"}, "VALIDATION_ERROR"),
        ({"article_type": "faq"}, "VALIDATION_ERROR"),
    ],
)
def test_create_validation(client, admin, body, code):
    payload = {"article_type": "troubleshooting", "category": "audio", "title": "T", "content": ""}
    r = client.post(f"{API}/knowledge-articles", json=payload | body, headers=admin)
    assert r.status_code == 422, r.text
    assert error_code(r) == code


def test_limits_are_inclusive_and_text_is_nfc(client, admin):
    nfd = unicodedata.normalize("NFD", "Йод ё")
    article = create_article(client, admin, title=nfd + "я" * (200 - len("Йод ё")))
    assert article["title"].startswith("Йод ё") and len(article["title"]) == 200
    assert create_article(client, admin, content="x" * 50_000)["content"] == "x" * 50_000
    tabs = create_article(client, admin, content="a\tb\r\nc")
    assert tabs["content"] == "a\tb\r\nc"


def test_binding_to_model_and_firmware(client, admin, owner, db: Session):
    zeekr = model_id(client, owner, "Zeekr")
    other = db.scalars(select(VehicleModel.id).where(VehicleModel.id != zeekr)).first()
    firmware = FirmwareRelease(
        vehicle_model_id=zeekr, version="5.1.0", released_at=date(2026, 9, 1)
    )
    db.add(firmware)
    db.commit()

    article = create_article(client, admin, vehicle_model_id=zeekr, firmware_release_id=firmware.id)
    assert (article["vehicle_model_id"], article["firmware_release_id"]) == (zeekr, firmware.id)
    for body in (
        {"firmware_release_id": firmware.id},  # прошивка без модели
        {"vehicle_model_id": other, "firmware_release_id": firmware.id},  # чужая модель
    ):
        r = client.post(
            f"{API}/knowledge-articles",
            json={"article_type": "guide", "title": "T", "content": ""} | body,
            headers=admin,
        )
        assert (r.status_code, error_code(r)) == (422, "FIRMWARE_RELEASE_NOT_FOUND"), body

    # PATCH: null снимает привязку; смена модели без прошивки — ошибка прошивки.
    r = client.patch(
        f"{API}/knowledge-articles/{article['id']}", json={"vehicle_model_id": other}, headers=admin
    )
    assert (r.status_code, error_code(r)) == (422, "FIRMWARE_RELEASE_NOT_FOUND")
    cleared = update_article(
        client, admin, article["id"], vehicle_model_id=None, firmware_release_id=None
    )
    assert (cleared["vehicle_model_id"], cleared["firmware_release_id"]) == (None, None)


@pytest.mark.parametrize(
    ("body", "code"),
    [
        ({"title": None}, "VALIDATION_ERROR"),
        ({"content": None}, "VALIDATION_ERROR"),
        ({"is_published": None}, "VALIDATION_ERROR"),
        ({"category": None}, "CATEGORY_REQUIRED"),
        ({"title": ""}, "VALIDATION_ERROR"),
    ],
)
def test_update_validation(client, admin, body, code):
    article = create_article(client, admin)
    r = client.patch(f"{API}/knowledge-articles/{article['id']}", json=body, headers=admin)
    assert r.status_code == 422, r.text
    assert error_code(r) == code


def test_update_changes_only_given_fields(client, admin):
    article = create_article(client, admin, title="Было", content="Текст", category="sim")
    updated = update_article(client, admin, article["id"], title="Стало")
    assert (updated["title"], updated["content"], updated["category"]) == ("Стало", "Текст", "sim")
    assert update_article(client, admin, article["id"])["title"] == "Стало"  # пустой PATCH


def test_missing_article_404(client, admin):
    for article_id in (10**9, 2**63, 0, -1):
        for method, op, body in (
            ("GET", "getKnowledgeArticle", None),
            ("PATCH", "updateKnowledgeArticle", {"title": "x"}),
            ("DELETE", "unpublishKnowledgeArticle", None),
        ):
            r = client.request(
                method, f"{API}/knowledge-articles/{article_id}", json=body, headers=admin
            )
            assert r.status_code == 404, (method, article_id)


# ---------- Доступ (RBAC-05) ----------


def test_draft_visible_only_to_admin(client, admin, engineer, owner):
    tree = api_tree(client, admin)
    article_id = tree["article"]["id"]
    for headers in (owner, engineer):
        for path, op in (
            (f"/knowledge-articles/{article_id}", "getKnowledgeArticle"),
            (f"/knowledge-articles/{article_id}/decision-tree", "listDecisionTreeNodes"),
        ):
            api(client, "GET", path, headers, op, 404)
        assert article_id not in ids(client, headers)
    api(
        client,
        "GET",
        f"/knowledge-articles/{article_id}/revisions",
        engineer,
        "listKnowledgeArticleRevisions",
        404,
    )
    assert article_id in ids(client, admin)

    publish(client, admin, article_id)
    for headers in (owner, engineer):
        got = api(
            client, "GET", f"/knowledge-articles/{article_id}", headers, "getKnowledgeArticle", 200
        )
        assert got["is_published"] is True
        nodes = api(
            client,
            "GET",
            f"/knowledge-articles/{article_id}/decision-tree",
            headers,
            "listDecisionTreeNodes",
            200,
        )
        assert len(nodes["items"]) == 3
        assert article_id in ids(client, headers)

    # Снятие с публикации: снова скрыта; повтор — тоже 204.
    for _ in range(2):
        api(
            client,
            "DELETE",
            f"/knowledge-articles/{article_id}",
            admin,
            "unpublishKnowledgeArticle",
            204,
        )
    api(client, "GET", f"/knowledge-articles/{article_id}", owner, "getKnowledgeArticle", 404)
    assert article_id not in ids(client, engineer)


def test_admin_operations_forbidden_for_others(client, admin, engineer, owner):
    tree = api_tree(client, admin)
    article_id, node_id = tree["article"]["id"], tree["solved"]["id"]
    node = {"question_text": "x", "is_root": False, "is_escalation": False}
    calls = [
        (
            "POST",
            "/knowledge-articles",
            "createKnowledgeArticle",
            {"article_type": "guide", "title": "x", "content": ""},
        ),
        ("PATCH", f"/knowledge-articles/{article_id}", "updateKnowledgeArticle", {"title": "x"}),
        ("DELETE", f"/knowledge-articles/{article_id}", "unpublishKnowledgeArticle", None),
        ("POST", f"/knowledge-articles/{article_id}/decision-tree", "createDecisionTreeNode", node),
        (
            "GET",
            f"/knowledge-articles/{article_id}/decision-tree/validate",
            "validateDecisionTree",
            None,
        ),
        ("PATCH", f"/decision-tree-nodes/{node_id}", "updateDecisionTreeNode", node),
        ("DELETE", f"/decision-tree-nodes/{node_id}", "deleteDecisionTreeNode", None),
    ]
    for headers in (owner, engineer):
        for method, path, op, body in calls:
            r = client.request(method, f"{API}{path}", json=body, headers=headers)
            assert r.status_code == 403, (method, path)
    for path, op in (
        (f"/knowledge-articles/{article_id}/revisions", "listKnowledgeArticleRevisions"),
        (f"/knowledge-articles/{article_id}/revisions/1", "getKnowledgeArticleRevision"),
    ):
        api(client, "GET", path, owner, op, 403)


# ---------- Версии (ADR 0018 п. 1) ----------


def revisions(client: TestClient, headers: Headers, article_id: int) -> list[dict]:
    body = api(
        client,
        "GET",
        f"/knowledge-articles/{article_id}/revisions",
        headers,
        "listKnowledgeArticleRevisions",
        200,
    )
    return body["items"]


def revision(client: TestClient, headers: Headers, article_id: int, version: int) -> dict:
    return api(
        client,
        "GET",
        f"/knowledge-articles/{article_id}/revisions/{version}",
        headers,
        "getKnowledgeArticleRevision",
        200,
    )


def test_version_is_published_revision(client, admin, engineer):
    tree = api_tree(client, admin, title="Версия 1")
    article_id = tree["article"]["id"]
    # Правки черновика версий не создают.
    assert update_article(client, admin, article_id, content="черновик")["version"] == 1
    assert revisions(client, admin, article_id) == []

    assert publish(client, admin, article_id)["version"] == 1
    assert publish(client, admin, article_id)["version"] == 1, "повторная публикация — без версии"
    assert update_article(client, admin, article_id, title="Версия 1")["version"] == 1
    assert update_article(client, admin, article_id, title="Версия 2")["version"] == 2
    assert update_article(client, admin, article_id, content="новый текст")["version"] == 3
    assert update_article(client, admin, article_id, category="sim")["version"] == 4

    items = revisions(client, engineer, article_id)
    assert [r["version"] for r in items] == [4, 3, 2, 1], "новые первыми"
    first = revision(client, engineer, article_id, 1)
    assert (first["title"], first["content"], first["category"]) == (
        "Версия 1",
        "черновик",
        "audio",
    )
    assert {n["id"] for n in first["decision_tree"]} == {
        tree[k]["id"] for k in ("root", "solved", "escalation")
    }
    assert all(n["article_id"] == article_id for n in first["decision_tree"])
    api(
        client,
        "GET",
        f"/knowledge-articles/{article_id}/revisions/99",
        admin,
        "getKnowledgeArticleRevision",
        404,
    )


def test_tree_change_creates_version_on_republish(client, admin):
    tree = api_tree(client, admin)
    article_id = tree["article"]["id"]
    publish(client, admin, article_id)
    api(
        client,
        "DELETE",
        f"/knowledge-articles/{article_id}",
        admin,
        "unpublishKnowledgeArticle",
        204,
    )
    # Снята с публикации: правки — черновик следующей версии.
    update_article(client, admin, article_id, title="Новая редакция")
    retry = create_node(
        client, admin, article_id, "Сбросьте настройки", [("Не помогло", tree["escalation"]["id"])]
    )
    api(
        client,
        "PATCH",
        f"/decision-tree-nodes/{tree['root']['id']}",
        admin,
        "updateDecisionTreeNode",
        200,
        json={
            "question_text": "Перезагрузили?",
            "is_root": True,
            "is_escalation": False,
            "options": [
                {"label": "Помогло", "next_node_id": tree["solved"]["id"]},
                {"label": "Не помогло", "next_node_id": retry["id"]},
            ],
        },
    )
    assert revisions(client, admin, article_id)[0]["version"] == 1, "черновик — без версии"

    assert publish(client, admin, article_id)["version"] == 2
    v2 = revision(client, admin, article_id, 2)
    assert v2["title"] == "Новая редакция" and len(v2["decision_tree"]) == 4
    assert len(revision(client, admin, article_id, 1)["decision_tree"]) == 3

    # Снять и опубликовать без изменений — версия прежняя.
    api(
        client,
        "DELETE",
        f"/knowledge-articles/{article_id}",
        admin,
        "unpublishKnowledgeArticle",
        204,
    )
    assert publish(client, admin, article_id)["version"] == 2


def test_engineer_reads_history_of_unpublished_article(client, admin, engineer):
    """Тикет может ссылаться на снятую статью (п. 11).

    Её версии персоналу открыты, черновое содержание — нет.
    """
    tree = api_tree(client, admin, title="Была опубликована")
    article_id = tree["article"]["id"]
    publish(client, admin, article_id)
    api(
        client,
        "DELETE",
        f"/knowledge-articles/{article_id}",
        admin,
        "unpublishKnowledgeArticle",
        204,
    )
    update_article(client, admin, article_id, title="Черновик следующей версии")
    assert revision(client, engineer, article_id, 1)["title"] == "Была опубликована"
    assert [r["version"] for r in revisions(client, engineer, article_id)] == [1]
    # Само черновое содержание инженеру не видно.
    api(client, "GET", f"/knowledge-articles/{article_id}", engineer, "getKnowledgeArticle", 404)
    never = api_tree(client, admin, title="Ни разу не публиковалась")["article"]["id"]
    api(
        client,
        "GET",
        f"/knowledge-articles/{never}/revisions",
        engineer,
        "listKnowledgeArticleRevisions",
        404,
    )


def test_revisions_are_append_only(client, admin, db: Session):
    tree = api_tree(client, admin)
    publish(client, admin, tree["article"]["id"])
    row = db.scalars(
        select(KnowledgeArticleRevision).where(
            KnowledgeArticleRevision.article_id == tree["article"]["id"]
        )
    ).one()
    row.title = "Подмена"
    with pytest.raises(Exception, match="append-only"):
        db.flush()
    db.rollback()
    with pytest.raises(Exception, match="append-only"):
        db.execute(
            delete(KnowledgeArticleRevision).where(
                KnowledgeArticleRevision.article_id == tree["article"]["id"]
            )
        )
    db.rollback()


def test_guide_publishes_without_tree(client, admin, owner):
    article = guide(client, admin)
    published = publish(client, admin, article["id"])
    assert (published["is_published"], published["version"]) == (True, 1)
    assert revision(client, admin, article["id"], 1)["decision_tree"] == []
    assert article["id"] in ids(client, owner, article_type="guide")


# ---------- Поиск и фильтры (ADR 0018 п. 9) ----------


def test_search_uses_russian_morphology_and_ranks_title(client, admin, engineer, db: Session):
    in_title = guide(client, admin, title="Обновление навигационных карт", content="Шаги.")
    in_text = guide(
        client,
        admin,
        title="Обновления по воздуху",
        content="После обновления навигационные карты загружаются заново.",
    )
    other = guide(client, admin, title="Bluetooth-гарнитура", content="Сопряжение.")
    for article in (in_title, in_text, other):
        publish(client, admin, article["id"])

    found = ids(client, engineer, search="навигационная карта")
    assert found[:2] == [in_title["id"], in_text["id"]], "совпадение в заголовке — выше"
    assert other["id"] not in found
    # Морфология: «обновлений» находит «обновление» и «обновления» (в тексте — дважды, выше).
    assert ids(client, engineer, search="обновлений")[:2] == [in_text["id"], in_title["id"]]
    assert ids(client, engineer, search="гарнитуры") == [other["id"]]
    assert ids(client, engineer, search='"навигационных карт" -воздуху') == [in_title["id"]]
    assert ids(client, engineer, search="несуществующееслово") == []


def test_blank_and_long_search(client, admin, engineer):
    article = publish(client, admin, guide(client, admin)["id"])
    assert article["id"] in ids(client, engineer, search="   ")
    assert ids(client, engineer, search="и") == [], "только стоп-слово — пустой запрос"
    assert ids(client, engineer, search="а" * 200) == []
    for bad in ("а" * 201, "NUL\x00", "CSI\x9b"):
        r = client.get(f"{API}/knowledge-articles", params={"search": bad}, headers=engineer)
        assert r.status_code == 422, repr(bad)


def test_search_is_nfc(client, admin, engineer):
    """Текст статей хранится в NFC: запрос в NFD («и» + U+0306) находит то же."""
    article = publish(client, admin, guide(client, admin, title="Йошкар настройка")["id"])
    for form in ("NFC", "NFD"):
        assert ids(client, engineer, search=unicodedata.normalize(form, "Йошкар")) == [
            article["id"]
        ], form


def test_filters(client, admin, engineer, owner):
    zeekr = model_id(client, owner, "Zeekr")
    voyah = model_id(client, owner, "Voyah")
    for_zeekr = guide(client, admin, title="Zeekr", vehicle_model_id=zeekr)
    for_voyah = guide(client, admin, title="Voyah", vehicle_model_id=voyah)
    general = guide(client, admin, title="Общая")
    sim = api_tree(client, admin, title="Связь", category="sim")["article"]
    draft = guide(client, admin, title="Черновик")
    for article in (for_zeekr, for_voyah, general, sim):
        publish(client, admin, article["id"])
    mine = {a["id"] for a in (for_zeekr, for_voyah, general, sim, draft)}

    zeekr_ids = set(ids(client, owner, vehicle_model_id=zeekr)) & mine
    assert zeekr_ids == {for_zeekr["id"], general["id"], sim["id"]}, "модель + общие"
    assert set(ids(client, owner, category="sim")) & mine == {sim["id"]}
    assert set(ids(client, owner, article_type="troubleshooting")) & mine == {sim["id"]}
    # is_published: персоналу — фильтр, клиенту — игнорируется, инженер черновиков не видит.
    assert set(ids(client, admin, is_published=False)) & mine == {draft["id"]}
    assert set(ids(client, admin, is_published=True)) & mine == mine - {draft["id"]}
    assert set(ids(client, engineer, is_published=False)) & mine == set()
    assert set(ids(client, owner, is_published=False)) & mine == mine - {draft["id"]}
    for params in ({"category": "weather"}, {"vehicle_model_id": 2**63}, {"article_type": "x"}):
        r = client.get(f"{API}/knowledge-articles", params=params, headers=owner)
        assert r.status_code == 422, params


def test_sorted_by_last_change(client, owner, db: Session):
    """Без поиска — свежие правки первыми, при равенстве — новые id первыми.

    Тест идёт в одной транзакции (now() не меняется), поэтому updated_at задан при вставке.
    """
    base = datetime(2026, 10, 1, tzinfo=UTC)
    rows = [
        KnowledgeArticle(
            article_type=KbArticleType.GUIDE,
            title=title,
            is_published=True,
            updated_at=base + timedelta(minutes=minutes),
        )
        for title, minutes in (("Старая", 0), ("Свежая", 10), ("Тоже старая", 0))
    ]
    db.add_all(rows)
    db.commit()
    mine = {r.id for r in rows}
    order = [i for i in ids(client, owner) if i in mine]
    assert order == [rows[1].id, rows[2].id, rows[0].id]
