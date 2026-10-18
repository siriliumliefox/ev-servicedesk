"""Тег Users (Глава 17, ADR 0021 п. 3): список, сотрудники, блокировка, последний администратор.

Ответы сверяет с контрактом `ContractClient` (conftest), здесь — правила домена.
"""

import threading
from datetime import UTC, datetime

from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import Session

from app.core.errors import ApiError
from app.domain.users import service
from app.models import AppUser, PushToken, RefreshToken
from app.models.enums import TicketStatus, UserRole
from tests.api.conftest import API, STAFF_PASSWORD, add_vehicle, bearer, code_from, register
from tests.api.ticket_support import create

ADMIN = "+375296600001"
ENGINEER = "+375296600002"
CLIENT = "+375296600003"
NEW_STAFF = "+375296600010"
PASSWORD = "Long-enough-pass-1"


def users(client, headers, **params) -> dict:
    r = client.get(f"{API}/users", params=params, headers=headers)
    assert r.status_code == 200, r.text
    return r.json()


def patch(client, headers, user_id: int, **body):
    return client.patch(f"{API}/users/{user_id}", json=body, headers=headers)


# ---------- Доступ ----------


def test_only_admin_manages_users(client, as_staff, as_client):
    eng_headers, eng = as_staff(ENGINEER)
    client_headers = as_client(CLIENT)
    for headers in (eng_headers, client_headers):
        assert client.get(f"{API}/users", headers=headers).status_code == 403
        assert client.get(f"{API}/users/{eng.id}", headers=headers).status_code == 403
        assert patch(client, headers, eng.id, is_active=False).status_code == 403
        r = client.post(
            f"{API}/users",
            json={"phone": NEW_STAFF, "role": "engineer", "password": PASSWORD},
            headers=headers,
        )
        assert r.status_code == 403


# ---------- Список и карточка ----------


def test_list_filters_and_pagination(client, as_staff, as_client, make_client_user):
    admin_headers, admin = as_staff(ADMIN, UserRole.ADMIN)
    _, eng = as_staff(ENGINEER)
    as_client(CLIENT)
    blocked = make_client_user("+375296600099", active=False)

    # Только пользователи этого теста (общая тестовая БД может содержать чужие строки).
    mine = {"search": "2966000"}
    everyone = users(client, admin_headers, **mine)
    assert everyone["meta"]["total_items"] == 4
    assert [u["id"] for u in everyone["items"]] == sorted(u["id"] for u in everyone["items"])
    assert admin.id in {u["id"] for u in everyone["items"]}

    engineers = users(client, admin_headers, role="engineer", **mine)["items"]
    assert [u["id"] for u in engineers] == [eng.id]
    inactive = users(client, admin_headers, is_active="false", **mine)["items"]
    assert [u["id"] for u in inactive] == [blocked.id]
    assert {u["phone"] for u in users(client, admin_headers, search="660000")["items"]} == {
        ADMIN,
        ENGINEER,
        CLIENT,
    }
    # Спецсимволы LIKE — обычные символы: «%» не совпадает ни с чем.
    assert users(client, admin_headers, search="%")["items"] == []

    page = users(client, admin_headers, page=2, page_size=3, **mine)
    assert page["meta"] == {"page": 2, "page_size": 3, "total_items": 4, "total_pages": 2}
    assert len(page["items"]) == 1


def test_get_user_and_not_found(client, as_staff):
    admin_headers, admin = as_staff(ADMIN, UserRole.ADMIN)
    r = client.get(f"{API}/users/{admin.id}", headers=admin_headers)
    assert r.status_code == 200
    assert r.json()["role"] == "admin"
    for missing in (admin.id + 1000, 2**63):
        r = client.get(f"{API}/users/{missing}", headers=admin_headers)
        assert r.status_code == 404
        assert r.json()["error"]["code"] == "USER_NOT_FOUND"


# ---------- Создание сотрудника ----------


def test_create_staff_user_can_log_in(client, as_staff):
    admin_headers, _ = as_staff(ADMIN, UserRole.ADMIN)
    r = client.post(
        f"{API}/users",
        json={"phone": NEW_STAFF, "role": "engineer", "password": PASSWORD},
        headers=admin_headers,
    )
    assert r.status_code == 201, r.text
    assert r.json()["role"] == "engineer" and r.json()["is_active"] is True
    login = client.post(f"{API}/auth/staff/login", json={"phone": NEW_STAFF, "password": PASSWORD})
    assert login.status_code == 200
    assert login.json()["user"]["id"] == r.json()["id"]


def test_create_staff_user_conflicts_and_validation(client, as_staff, as_client):
    admin_headers, _ = as_staff(ADMIN, UserRole.ADMIN)
    as_client(CLIENT)
    for phone in (ADMIN, CLIENT):
        r = client.post(
            f"{API}/users",
            json={"phone": phone, "role": "engineer", "password": PASSWORD},
            headers=admin_headers,
        )
        assert r.status_code == 409
        assert r.json()["error"]["code"] == "PHONE_ALREADY_REGISTERED"
    for body in (
        {"phone": NEW_STAFF, "role": "client", "password": PASSWORD},  # клиенты — сами
        {"phone": NEW_STAFF, "role": "engineer", "password": "short"},
        {"phone": "375296600010", "role": "engineer", "password": PASSWORD},
    ):
        assert client.post(f"{API}/users", json=body, headers=admin_headers).status_code == 422


# ---------- Роль и последний администратор ----------


def test_role_change_between_staff_roles(client, as_staff):
    admin_headers, _ = as_staff(ADMIN, UserRole.ADMIN)
    eng_headers, eng = as_staff(ENGINEER)
    r = patch(client, admin_headers, eng.id, role="admin")
    assert r.status_code == 200 and r.json()["role"] == "admin"
    # Роль читается из БД: прежний access-токен сразу получает права администратора.
    assert client.get(f"{API}/users", headers=eng_headers).status_code == 200
    r = patch(client, admin_headers, eng.id, role="engineer")
    assert r.status_code == 200 and r.json()["role"] == "engineer"
    assert client.get(f"{API}/users", headers=eng_headers).status_code == 403


def test_client_role_cannot_change(client, as_staff, as_client, db):
    admin_headers, _ = as_staff(ADMIN, UserRole.ADMIN)
    as_client(CLIENT)
    client_id = users(client, admin_headers, role="client")["items"][0]["id"]
    for role in ("engineer", "admin"):
        r = patch(client, admin_headers, client_id, role=role)
        assert r.status_code == 409
        assert r.json()["error"]["code"] == "ROLE_CHANGE_NOT_ALLOWED"
    _, eng = as_staff(ENGINEER)
    r = client.patch(f"{API}/users/{eng.id}", json={"role": "client"}, headers=admin_headers)
    assert r.status_code == 422  # client в UserUpdateRequest не допускается схемой


def test_empty_update_is_rejected(client, as_staff):
    admin_headers, admin = as_staff(ADMIN, UserRole.ADMIN)
    for body in ({}, {"role": None}, {"is_active": None}):
        assert patch(client, admin_headers, admin.id, **body).status_code == 422


def test_last_admin_cannot_be_demoted_or_blocked(client, as_staff):
    admin_headers, admin = as_staff(ADMIN, UserRole.ADMIN)
    for body in ({"role": "engineer"}, {"is_active": False}):
        r = patch(client, admin_headers, admin.id, **body)
        assert r.status_code == 409
        assert r.json()["error"]["code"] == "LAST_ADMIN"
    # Подтверждение текущего состояния — не понижение.
    assert patch(client, admin_headers, admin.id, role="admin", is_active=True).status_code == 200

    _, second = as_staff("+375296600004", UserRole.ADMIN)
    assert patch(client, admin_headers, second.id, is_active=False).status_code == 200
    # Заблокированный администратор не считается: первый снова последний.
    r = patch(client, admin_headers, admin.id, role="engineer")
    assert r.json()["error"]["code"] == "LAST_ADMIN"
    assert patch(client, admin_headers, second.id, is_active=True).status_code == 200
    r = patch(client, admin_headers, admin.id, role="engineer")
    assert r.status_code == 200


# ---------- Блокировка (глоссарий «Блокировка пользователя») ----------


def test_blocking_client_ends_sessions_and_push(client, as_staff, login_client, db):
    admin_headers, _ = as_staff(ADMIN, UserRole.ADMIN)
    session = login_client(CLIENT)
    headers = bearer(session["access_token"])
    register(client, headers, "fcm-block:" + "x" * 40)
    client_id = client.get(f"{API}/me", headers=headers).json()["id"]

    r = patch(client, admin_headers, client_id, is_active=False)
    assert r.status_code == 200 and r.json()["is_active"] is False

    assert client.get(f"{API}/me", headers=headers).status_code == 401
    refresh = client.post(f"{API}/auth/refresh", json={"refresh_token": session["refresh_token"]})
    assert refresh.status_code == 401
    assert (
        db.scalars(
            select(RefreshToken).where(
                RefreshToken.user_id == client_id, RefreshToken.revoked_at.is_(None)
            )
        ).all()
        == []
    )
    assert (
        db.scalars(
            select(PushToken).where(PushToken.user_id == client_id, PushToken.revoked_at.is_(None))
        ).all()
        == []
    )

    # Разблокировка возвращает вход, но не прежние сессии.
    assert patch(client, admin_headers, client_id, is_active=True).status_code == 200
    again = client.post(f"{API}/auth/refresh", json={"refresh_token": session["refresh_token"]})
    assert again.status_code == 401


def test_blocked_client_cannot_log_in_until_unblocked(client, as_staff, make_client_user, sms):
    admin_headers, _ = as_staff(ADMIN, UserRole.ADMIN)
    user = make_client_user(CLIENT)
    # Код выпущен до блокировки: заблокированному SMS уже не отправляется (#103).
    client.post(f"{API}/auth/phone/request-code", json={"phone": CLIENT})
    body = {"phone": CLIENT, "code": code_from(sms, CLIENT)}
    assert patch(client, admin_headers, user.id, is_active=False).status_code == 200
    r = client.post(f"{API}/auth/phone/verify-code", json=body)
    assert r.status_code == 400 and r.json()["error"]["code"] == "ACCOUNT_DISABLED"
    # Отказ не расходует код: после разблокировки тот же код входит.
    assert patch(client, admin_headers, user.id, is_active=True).status_code == 200
    r = client.post(f"{API}/auth/phone/verify-code", json=body)
    assert r.status_code == 200 and r.json()["access_token"]


def test_blocked_staff_cannot_log_in(client, as_staff):
    admin_headers, _ = as_staff(ADMIN, UserRole.ADMIN)
    eng_headers, eng = as_staff(ENGINEER)
    assert patch(client, admin_headers, eng.id, is_active=False).status_code == 200
    assert client.get(f"{API}/me", headers=eng_headers).status_code == 401
    r = client.post(f"{API}/auth/staff/login", json={"phone": ENGINEER, "password": STAFF_PASSWORD})
    assert r.status_code == 401


def test_blocked_engineer_keeps_tickets_until_reassigned(client, as_staff, as_client):
    admin_headers, _ = as_staff(ADMIN, UserRole.ADMIN)
    eng_headers, eng = as_staff(ENGINEER)
    _, other = as_staff("+375296600005")
    owner = as_client(CLIENT)
    vehicle = add_vehicle(client, owner)
    ticket = create(client, owner, vehicle["id"], category="sim", description="Нет сети")
    claim = client.post(f"{API}/tickets/{ticket['id']}/claim", headers=eng_headers)
    assert claim.status_code == 200

    assert patch(client, admin_headers, eng.id, is_active=False).status_code == 200
    card = client.get(f"{API}/tickets/{ticket['id']}", headers=admin_headers).json()
    assert card["assigned_engineer_id"] == eng.id
    assert card["status"] == TicketStatus.IN_PROGRESS.value

    # Назначить заблокированного нельзя, переназначить его тикет другому — можно.
    r = client.patch(
        f"{API}/tickets/{ticket['id']}/assign",
        json={"assigned_engineer_id": eng.id},
        headers=admin_headers,
    )
    assert r.status_code == 422
    r = client.patch(
        f"{API}/tickets/{ticket['id']}/assign",
        json={"assigned_engineer_id": other.id},
        headers=admin_headers,
    )
    assert r.status_code == 200 and r.json()["assigned_engineer_id"] == other.id


# ---------- Гонка: последний администратор ----------


def test_parallel_demotions_keep_one_admin(migrated_engine, real_redis, settings):
    """Два администратора одновременно понижают друг друга: один получает 409 LAST_ADMIN.

    Без блокировки строк всех активных администраторов оба видят «администраторов два» и
    система остаётся без администратора.
    """
    with Session(migrated_engine) as setup:
        assert not setup.scalar(
            select(func.count()).select_from(AppUser).where(AppUser.role == UserRole.ADMIN)
        ), "в тестовой БД остались закоммиченные администраторы"
        admins = [
            AppUser(phone=f"+37529661000{i}", role=UserRole.ADMIN, password_hash="x")
            for i in (1, 2)
        ]
        setup.add_all(admins)
        setup.commit()
        ids = [a.id for a in admins]

    def demote(target: int):
        def run():
            with Session(migrated_engine) as s:
                return service.update_user(
                    s, real_redis, settings, target, UserRole.ENGINEER, None
                ).role

        return run

    try:
        for _ in range(5):
            results = storm_each([demote(ids[0]), demote(ids[1])])
            codes = sorted(r.code if isinstance(r, ApiError) else "ok" for r in results)
            assert codes == ["LAST_ADMIN", "ok"], results
            with Session(migrated_engine) as s:
                assert (
                    s.scalar(
                        select(func.count())
                        .select_from(AppUser)
                        .where(AppUser.role == UserRole.ADMIN, AppUser.is_active.is_(True))
                    )
                    == 1
                )
                s.execute(update(AppUser).where(AppUser.id.in_(ids)).values(role=UserRole.ADMIN))
                s.commit()
    finally:
        with Session(migrated_engine) as cleanup:
            cleanup.execute(delete(AppUser).where(AppUser.id.in_(ids)))
            cleanup.commit()


def storm_each(fns: list) -> list[object]:
    """Функции стартуют одновременно; результат — значение или исключение."""
    barrier = threading.Barrier(len(fns))
    results: list[object] = [None] * len(fns)

    def run(i: int) -> None:
        barrier.wait()
        try:
            results[i] = fns[i]()
        except Exception as exc:  # noqa: BLE001 — исход каждого вызова нужен тесту
            results[i] = exc

    threads = [threading.Thread(target=run, args=(i,)) for i in range(len(fns))]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    return results


# ---------- Сброс пароля сотрудника (контракт 1.11.0, ADR 0026 п. 5) ----------

NEW_PASSWORD = "Brand-new-pass-22"


def reset(client, headers, user_id: int, password: str = NEW_PASSWORD):
    return client.post(
        f"{API}/users/{user_id}/password", json={"password": password}, headers=headers
    )


def staff_login(client, phone: str, password: str):
    return client.post(f"{API}/auth/staff/login", json={"phone": phone, "password": password})


def test_reset_password_replaces_password_and_ends_sessions(client, as_staff):
    admin_headers, _ = as_staff(ADMIN, UserRole.ADMIN)
    _, eng = as_staff(ENGINEER)
    session = staff_login(client, ENGINEER, STAFF_PASSWORD).json()

    r = reset(client, admin_headers, eng.id)
    assert r.status_code == 204 and r.content == b""

    assert staff_login(client, ENGINEER, STAFF_PASSWORD).status_code == 401
    assert staff_login(client, ENGINEER, NEW_PASSWORD).status_code == 200
    # Прежняя сессия закончилась: refresh отозван.
    r = client.post(f"{API}/auth/refresh", json={"refresh_token": session["refresh_token"]})
    assert r.status_code == 401


def test_reset_password_of_blocked_staff_works_after_unblock(client, as_staff):
    admin_headers, _ = as_staff(ADMIN, UserRole.ADMIN)
    _, eng = as_staff(ENGINEER)
    assert patch(client, admin_headers, eng.id, is_active=False).status_code == 200
    assert reset(client, admin_headers, eng.id).status_code == 204
    assert staff_login(client, ENGINEER, NEW_PASSWORD).status_code == 401
    assert patch(client, admin_headers, eng.id, is_active=True).status_code == 200
    assert staff_login(client, ENGINEER, NEW_PASSWORD).status_code == 200


def test_reset_password_rules(client, as_staff, as_client, make_client_user, make_staff, db):
    admin_headers, admin = as_staff(ADMIN, UserRole.ADMIN)
    eng_headers, eng = as_staff(ENGINEER)
    client_headers = as_client(CLIENT)
    customer = db.scalars(select(AppUser).where(AppUser.phone == CLIENT)).one()

    # Только admin.
    for headers in (eng_headers, client_headers):
        assert reset(client, headers, eng.id).status_code == 403
    # У клиента пароля нет.
    r = reset(client, admin_headers, customer.id)
    assert r.status_code == 409 and r.json()["error"]["code"] == "PASSWORD_NOT_ALLOWED"
    # Нет пользователя или он анонимизирован.
    gone = make_staff("+375296600020")
    gone.anonymized_at = datetime.now(UTC)
    db.commit()
    for missing in (admin.id + 1000, gone.id):
        r = reset(client, admin_headers, missing)
        assert r.status_code == 404 and r.json()["error"]["code"] == "USER_NOT_FOUND"
    # Длина пароля — как при создании.
    for bad in ("x" * 11, "x" * 129):
        assert reset(client, admin_headers, eng.id, bad).status_code == 422
    r = client.post(f"{API}/users/{eng.id}/password", json={}, headers=admin_headers)
    assert r.status_code == 422
    # Старый пароль инженера не тронут отказами.
    assert staff_login(client, ENGINEER, STAFF_PASSWORD).status_code == 200
