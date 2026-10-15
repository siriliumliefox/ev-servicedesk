"""Сид нагрузочного стенда (глава 24, ADR 0028 п. 6, 7): объём и токены, которыми идёт нагрузка.

Уменьшенный объём (100 клиентов): связи данных и токены те же, что на стенде с 10 000.
"""

from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import Settings
from scripts.seed_load import ADMINS, ARTICLES, ENGINEERS, refuse_production, seed, sessions
from tests.api.conftest import API, bearer

CLIENTS = 100


@pytest.fixture
def seeded(db: Session, settings: Settings) -> dict:
    return seed(db, settings, CLIENTS)


def count(db: Session, sql: str) -> int:
    return db.execute(text(sql)).scalar_one()


def test_volume_matches_adr(db: Session, seeded: dict) -> None:
    load = "FROM ticket t JOIN vehicle v ON v.id = t.vehicle_id WHERE v.vin LIKE 'LDTS%'"
    assert len(seeded["clients"]) == CLIENTS
    assert count(db, f"SELECT count(*) {load}") == CLIENTS * 2
    assert (
        count(db, f"SELECT count(*) FROM ticket_message WHERE ticket_id IN (SELECT t.id {load})")
        == CLIENTS * 6
    )
    open_statuses = count(db, f"SELECT count(*) {load} AND t.status IN ('new', 'in_progress')")
    assert 0 < open_statuses < CLIENTS, "открыта только последняя неделя"
    assert count(db, f"SELECT count(*) {load} AND t.status = 'resolved'") > CLIENTS
    deliveries = (
        "SELECT count(*) FROM notification_delivery d"
        " JOIN push_token p ON p.id = d.push_token_id WHERE p.token LIKE 'load-%'"
    )
    assert count(db, deliveries) == CLIENTS * 3
    assert len(seeded["engineers"]) == ENGINEERS
    assert len(seeded["admins"]) == ADMINS
    assert len(seeded["articles"]) == ARTICLES
    statuses = count(
        db,
        "SELECT count(DISTINCT s.id) FROM vehicle_aggregate_status s JOIN vehicle v"
        " ON v.id = s.vehicle_id WHERE v.vin LIKE 'LDTS%'",
    )
    assert statuses == CLIENTS * count(db, "SELECT count(*) FROM aggregate_type")


def test_seeded_tokens_work_like_login(client: TestClient, seeded: dict) -> None:
    owner = seeded["clients"][7]
    r = client.get(f"{API}/vehicles", headers=bearer(owner["access"]))
    assert r.status_code == 200, r.text
    assert [v["id"] for v in r.json()["items"]] == [owner["vehicle_id"]]
    r = client.get(
        f"{API}/vehicles/{owner['vehicle_id']}/aggregate-statuses", headers=bearer(owner["access"])
    )
    assert r.status_code == 200, r.text
    colors = {s["status"] for s in r.json()["items"]}
    assert colors - {"unknown"}, "статусы считаются по регламентам"

    engineer = seeded["engineers"][0]["sessions"][3]
    r = client.get(f"{API}/tickets", headers=bearer(engineer["access"]))
    assert r.status_code == 200, r.text
    assert r.json()["items"], "у инженера есть очередь и свои тикеты"

    admin = seeded["admins"][0]["sessions"][0]
    r = client.get(f"{API}/users", headers=bearer(admin["access"]))
    assert r.status_code == 200, r.text

    # Сессии независимы: ротация одной не отзывает другие (reuse detection не срабатывает).
    for session in seeded["engineers"][1]["sessions"][:2]:
        r = client.post(f"{API}/auth/refresh", json={"refresh_token": session["refresh"]})
        assert r.status_code == 200, r.text


def test_next_scenario_gets_fresh_sessions(
    client: TestClient, db: Session, settings: Settings, seeded: dict
) -> None:
    """Сценарий повернул refresh-токены — следующий получает новые (--tokens-only)."""
    used = seeded["clients"][3]["refresh"]
    assert client.post(f"{API}/auth/refresh", json={"refresh_token": used}).status_code == 200
    fresh = sessions(db, settings)
    assert fresh["articles"] == seeded["articles"]
    assert len(fresh["clients"]) == CLIENTS
    r = client.post(f"{API}/auth/refresh", json={"refresh_token": fresh["clients"][3]["refresh"]})
    assert r.status_code == 200, r.text


def test_seed_refuses_production() -> None:
    with pytest.raises(SystemExit, match="production"):
        refuse_production(SimpleNamespace(environment="production"))  # type: ignore[arg-type]
