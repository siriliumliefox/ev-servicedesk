"""Планы запросов нагрузочного профиля (глава 24, ADR 0028 п. 16): защита от регресса.

На объёме нагрузочного стенда (seed_load, 10 000 клиентов, 20 000 тикетов, 60 000 сообщений)
проходят операции, которые k6 вызывает чаще всего, — от имени клиента, инженера и
администратора. Каждый SQL-запрос операции перехватывается и проверяется EXPLAIN: по таблицам
от MIN_ROWS строк нет полного сканирования (Seq Scan), кроме осознанных (ALLOWED). Новый запрос
без индекса падает здесь, а не под нагрузкой.
"""

from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event
from sqlalchemy.orm import Session

from app.core.config import Settings
from scripts.seed_load import seed
from tests.api.conftest import API, bearer

CLIENTS = 10_000
# Полное чтение таблицы, в которой по статистике меньше строк, — выбор планировщика, а не дефект:
# справочники, статьи базы знаний (сотни), вложения в тестовом объёме.
MIN_ROWS = 1_000
# Осознанные полные чтения: (фрагмент запроса, таблица, причина).
ALLOWED = (
    (
        "SELECT count(*) AS count_1 FROM (SELECT app_user.id",
        "app_user",
        "всего пользователей для списка без фильтра в админ-панели — подсчёт и есть чтение всех",
    ),
    # Статистика доставки страницы рассылок: читаются все строки получателей и доставок этих
    # рассылок (у рассылки на модель — тысячи), на тестовом объёме это заметная доля таблицы,
    # и планировщик по статистике выбирает Seq Scan. Индекс по notification_id есть (UNIQUE).
    (
        "SELECT notification_recipient.notification_id, count(*)",
        "notification_recipient",
        "получатели последних рассылок — заметная доля таблицы",
    ),
    (
        "SELECT notification_delivery.notification_id, count(notification_delivery.delivered_at)",
        "notification_delivery",
        "доставки последних рассылок — заметная доля таблицы",
    ),
)


@pytest.fixture
def seeded(db: Session, settings: Settings) -> dict:
    return seed(db, settings, CLIENTS)


@pytest.fixture
def captured(db: Session) -> Iterator[list[tuple[str, Any]]]:
    """SQL-запросы, выполненные на соединении теста (запросы API идут через него же)."""
    statements: list[tuple[str, Any]] = []
    connection = db.connection()

    def remember(_conn, _cursor, statement, parameters, _context, _executemany) -> None:
        if statement.lstrip().upper().startswith(("SELECT", "UPDATE", "DELETE", "WITH")):
            statements.append((statement, parameters))

    event.listen(connection, "before_cursor_execute", remember)
    yield statements
    event.remove(connection, "before_cursor_execute", remember)


def seq_scans(plan: dict, rows: dict[str, float]) -> list[str]:
    found = []
    table = plan.get("Relation Name")
    if plan.get("Node Type") == "Seq Scan" and rows.get(table, 0) >= MIN_ROWS:
        found.append(table)
    for child in plan.get("Plans", []):
        found += seq_scans(child, rows)
    return found


def allowed(sql: str, table: str) -> bool:
    return any(sql.startswith(fragment) and table == t for fragment, t, _ in ALLOWED)


def explain_all(db: Session, statements: list[tuple[str, Any]]) -> dict[str, list[str]]:
    """Запрос → большие таблицы, читаемые целиком (EXPLAIN без ANALYZE — ничего не меняет)."""
    connection = db.connection()
    rows = {
        name: count
        for name, count in connection.exec_driver_sql(
            "SELECT relname, reltuples FROM pg_class WHERE relkind = 'r'"
            " AND relnamespace = 'public'::regnamespace"
        ).tuples()
    }
    bad: dict[str, list[str]] = {}
    for statement, parameters in statements:
        result = connection.exec_driver_sql(f"EXPLAIN (FORMAT JSON) {statement}", parameters)
        sql = " ".join(statement.split())
        plan = result.scalar_one()[0]["Plan"]  # psycopg разбирает JSON сам
        tables = [t for t in seq_scans(plan, rows) if not allowed(sql, t)]
        if tables:
            bad[sql[:300]] = tables
    return bad


def run_profile(client: TestClient, seeded: dict) -> None:
    """Операции нагрузочного профиля (load/lib/roles.js) — по одной от каждой роли."""
    owner = seeded["clients"][4321]
    c = bearer(owner["access"])
    vehicle = owner["vehicle_id"]
    for path in (
        "/me",
        "/vehicles",
        f"/vehicles/{vehicle}/aggregate-statuses",
        f"/vehicles/{vehicle}/maintenance-records",
        "/notifications?page_size=20",
        "/tickets?page_size=20",
        "/knowledge-articles?is_published=true&page_size=20",
        f"/knowledge-articles/{seeded['articles'][7]}",
        "/knowledge-articles?is_published=true&search=руководство",
    ):
        assert client.get(f"{API}{path}", headers=c).status_code == 200, path
    tickets = client.get(f"{API}/tickets?page_size=20", headers=c).json()["items"]
    ticket = tickets[0]["id"]
    assert client.get(f"{API}/tickets/{ticket}/messages?page_size=50", headers=c).status_code == 200
    r = client.post(
        f"{API}/tickets",
        json={"vehicle_id": vehicle, "category": "audio", "description": "Не работает звук"},
        headers=c,
    )
    assert r.status_code == 201, r.text
    new_ticket = r.json()["id"]

    e = bearer(seeded["engineers"][0]["sessions"][0]["access"])
    for status in ("new", "in_progress", "waiting_vendor"):
        r = client.get(f"{API}/tickets?status={status}&page_size=100", headers=e)
        assert r.status_code == 200, r.text
    r = client.get(
        f"{API}/tickets?status=resolved&page_size=100&resolved_since=2026-01-01T00:00:00Z",
        headers=e,
    )
    assert r.status_code == 200, r.text
    assert client.get(f"{API}/tickets/{new_ticket}", headers=e).status_code == 200
    assert client.post(f"{API}/tickets/{new_ticket}/claim", headers=e).status_code == 200
    r = client.post(
        f"{API}/tickets/{new_ticket}/messages", json={"body": "Проверьте ещё раз"}, headers=e
    )
    assert r.status_code == 201, r.text

    a = bearer(seeded["admins"][0]["sessions"][0]["access"])
    period = "date_from=2026-09-01&date_to=2026-09-30"
    for path in (
        f"/analytics/ticket-resolution?{period}",
        f"/analytics/problem-models?{period}",
        f"/analytics/maintenance-conversion?{period}",
        "/notifications/published?page_size=20",
        "/users?page_size=50",
    ):
        assert client.get(f"{API}{path}", headers=a).status_code == 200, path
    r = client.post(f"{API}/auth/refresh", json={"refresh_token": owner["refresh"]})
    assert r.status_code == 200, r.text


def test_load_profile_has_no_full_scans_of_big_tables(
    client: TestClient, db: Session, seeded: dict, captured: list[tuple[str, Any]]
) -> None:
    run_profile(client, seeded)
    assert len(captured) > 40, "запросы операций перехвачены"
    bad = explain_all(db, captured)
    assert not bad, "Seq Scan по большим таблицам:\n" + "\n".join(
        f"- {tables}: {sql}" for sql, tables in bad.items()
    )
