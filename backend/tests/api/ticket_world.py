"""Участники и тикеты тестов доступа и ПД Tickets Service (Глава 13, ADR 0017, RBAC-04).

Обычный модуль без фикстур: test_ticket_security.py и test_ticket_privacy.py строят мир
своей фикстурой `world` через build_world. Токены — настоящие (Глава 10): клиент входит
по SMS-коду, персонал — по паролю.
"""

from collections.abc import Callable
from dataclasses import dataclass

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models import AppUser, Ticket
from app.models.enums import UserRole
from tests.api.conftest import API, ZEEKR_VIN, Headers, add_vehicle, bearer
from tests.api.ticket_support import create

OWNER, STRANGER, EX_OWNER = "owner", "stranger", "ex_owner"  # клиенты
ENGINEER, OTHER_ENGINEER, ADMIN = "engineer", "other_engineer", "admin"  # персонал
CLIENTS = (OWNER, STRANGER, EX_OWNER)
STAFF = {ENGINEER: UserRole.ENGINEER, OTHER_ENGINEER: UserRole.ENGINEER, ADMIN: UserRole.ADMIN}
PHONES = {
    OWNER: "+375296610001",
    STRANGER: "+375296610002",
    EX_OWNER: "+375296610003",
    ENGINEER: "+375296610004",
    OTHER_ENGINEER: "+375296610005",
    ADMIN: "+375296610006",
}
VINS = {OWNER: ZEEKR_VIN, STRANGER: "L6TZ0010000000002", EX_OWNER: "L6TZ0010000000003"}

# Тикеты на авто владельца: очередь (new без исполнителя), назначенный инженеру, назначенный
# другому инженеру; тикет бывшего владельца на удалённом (проданном) авто — у инженера.
QUEUE, ASSIGNED, OTHERS, DELETED_VEHICLE = "queue", "assigned", "others", "deleted_vehicle"


@dataclass
class World:
    tokens: dict[str, str]  # участник → access-токен настоящего входа
    users: dict[str, AppUser]
    vehicles: dict[str, int]  # клиент → его авто (у EX_OWNER — удалённое)
    tickets: dict[str, int]
    assignees: dict[str, int | None]  # тикет → исполнитель
    refresh_token: str  # владельца

    def headers(self, actor: str) -> Headers:
        return bearer(self.tokens[actor])


def build_world(
    client: TestClient,
    login_client: Callable[[str], dict],
    as_staff: Callable[..., tuple[Headers, AppUser]],
    make_ticket: Callable[..., Ticket],
    db: Session,
) -> World:
    tokens: dict[str, str] = {}
    users: dict[str, AppUser] = {}
    refresh_token = ""
    for actor in CLIENTS:
        session = login_client(PHONES[actor])
        tokens[actor] = session["access_token"]
        users[actor] = db.get_one(AppUser, session["user"]["id"])
        if actor == OWNER:
            refresh_token = session["refresh_token"]
    for actor, role in STAFF.items():
        headers, user = as_staff(PHONES[actor], role)
        tokens[actor] = headers["Authorization"].removeprefix("Bearer ")
        users[actor] = user
    vehicles = {
        actor: add_vehicle(client, bearer(tokens[actor]), VINS[actor])["id"] for actor in CLIENTS
    }

    def new_ticket(actor: str) -> int:
        body = {"category": "sim", "description": "Нет сети"}
        return create(client, bearer(tokens[actor]), vehicles[actor], **body)["id"]

    tickets = {
        QUEUE: new_ticket(OWNER),
        ASSIGNED: make_ticket(vehicles[OWNER], users[ENGINEER]).id,
        OTHERS: make_ticket(vehicles[OWNER], users[OTHER_ENGINEER]).id,
        DELETED_VEHICLE: new_ticket(EX_OWNER),
    }
    # Бывший владелец успел пообщаться с инженером, затем удалил авто (продажа, ADR 0003).
    sold = tickets[DELETED_VEHICLE]
    r = client.post(f"{API}/tickets/{sold}/claim", headers=bearer(tokens[ENGINEER]))
    assert r.status_code == 200, r.text
    r = client.post(
        f"{API}/tickets/{sold}/messages",
        json={"body": "Продаю авто"},
        headers=bearer(tokens[EX_OWNER]),
    )
    assert r.status_code == 201, r.text
    r = client.delete(f"{API}/vehicles/{vehicles[EX_OWNER]}", headers=bearer(tokens[EX_OWNER]))
    assert r.status_code == 204, r.text

    assignees = {
        QUEUE: None,
        ASSIGNED: users[ENGINEER].id,
        OTHERS: users[OTHER_ENGINEER].id,
        DELETED_VEHICLE: users[ENGINEER].id,
    }
    return World(tokens, users, vehicles, tickets, assignees, refresh_token)
