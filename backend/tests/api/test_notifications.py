"""Notifications Service (Глава 15, ADR 0019): API, таргетинг, токены, лента, журнал.

Тест чек-листа «уведомление для модели X не приходит владельцам модели Y» —
`test_targeting_model_x_not_y`. Отправка push — worker с фейковым отправителем
(tests/api/test_notifications_worker.py — очередь, повторы, cron и push по тикетам).
Каждый ответ сверяется со схемой docs/openapi.yaml (`assert_contract`).
"""

import unicodedata
from datetime import UTC, date, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.aggregates.service import today_in_business_tz
from app.domain.notifications.push import Outcome, PushResult
from app.models import (
    AppUser,
    NotificationDelivery,
    NotificationRecipient,
    PdConsent,
    PushToken,
)
from app.models.enums import UserRole
from tests.api.conftest import API, Headers, model_id, register
from tests.api.notifications_support import feed, publish
from tests.api.ticket_support import error_code


@pytest.fixture
def admin(as_staff) -> Headers:
    return as_staff("+375293390001", UserRole.ADMIN)[0]


@pytest.fixture
def engineer(as_staff) -> tuple[Headers, AppUser]:
    return as_staff("+375293390002")


def zeekr(client: TestClient, admin: Headers) -> int:
    return model_id(client, admin, "Zeekr")


def voyah(client: TestClient, admin: Headers) -> int:
    return model_id(client, admin, "Voyah")


def preview(client: TestClient, admin: Headers, **body) -> dict:
    r = client.post(f"{API}/notifications/audience-preview", json=body, headers=admin)
    assert r.status_code == 200, r.text
    return r.json()


def release(client: TestClient, admin: Headers, model: int, version: str, released_at: date):
    r = client.post(
        f"{API}/firmware-releases",
        json={"vehicle_model_id": model, "version": version, "released_at": str(released_at)},
        headers=admin,
    )
    return r


def tokens_of(db: Session, notification_id: int) -> set[str]:
    return set(
        db.scalars(
            select(PushToken.token)
            .join(NotificationDelivery, NotificationDelivery.push_token_id == PushToken.id)
            .where(NotificationDelivery.notification_id == notification_id)
        )
    )


# ---------- Тест чек-листа: таргетинг по модели ----------


def test_targeting_model_x_not_y(client, admin, make_owner, make_worker, sender, db: Session):
    x = make_owner("Zeekr")
    y = make_owner("Voyah")
    body = {"type": "news", "target_vehicle_model_id": zeekr(client, admin), "message": "Акция X"}
    assert preview(client, admin, **body) == {"recipients": 1, "devices": 1}

    news = publish(client, admin, **body)
    assert news["target_vehicle_model_id"] == body["target_vehicle_model_id"]
    assert news["vehicle_id"] is None and news["aggregate_type_id"] is None

    assert [n["id"] for n in feed(client, x.headers)["items"]] == [news["id"]]
    assert feed(client, y.headers)["items"] == []
    assert tokens_of(db, news["id"]) == {x.token}

    make_worker().dispatch()
    assert [m.body for m in sender.to(x.token)] == ["Акция X"]
    assert sender.to(y.token) == []
    assert sender.to(x.token)[0].title == "Новости"
    assert sender.to(x.token)[0].data == {"notification_id": str(news["id"]), "type": "news"}


def test_all_models_reach_only_eligible_clients(
    client, admin, make_owner, make_client_user, db: Session
):
    with_car = make_owner("Zeekr")
    no_car = make_owner(None)
    withdrawn = make_owner("Voyah")
    r = client.delete(f"{API}/auth/pd-consent", headers=withdrawn.headers)
    assert r.status_code == 202, r.text
    inactive = make_client_user("+375293390050", active=False)
    no_consent = make_client_user("+375293390051", consent=False)

    body = {"type": "promo", "target_vehicle_model_id": None, "message": "Скидка на ТО"}
    assert preview(client, admin, **body) == {"recipients": 2, "devices": 2}
    promo = publish(client, admin, **body)
    users = set(
        db.scalars(
            select(NotificationRecipient.user_id).where(
                NotificationRecipient.notification_id == promo["id"]
            )
        )
    )
    me = {
        client.get(f"{API}/me", headers=h).json()["id"] for h in (with_car.headers, no_car.headers)
    }
    assert users == me
    assert inactive.id not in users and no_consent.id not in users
    assert tokens_of(db, promo["id"]) == {with_car.token, no_car.token}


def test_client_with_two_cars_of_model_gets_one_notification(
    client, admin, make_owner, db: Session
):
    owner = make_owner("Zeekr")
    r = client.post(f"{API}/vehicles", json={"vin": "L6TZ0019999999999"}, headers=owner.headers)
    assert r.status_code == 201, r.text
    news = publish(
        client, admin, type="news", target_vehicle_model_id=zeekr(client, admin), message="Да"
    )
    assert len(feed(client, owner.headers)["items"]) == 1
    assert tokens_of(db, news["id"]) == {owner.token}


def test_deleted_vehicle_leaves_audience(client, admin, make_owner):
    owner = make_owner("Zeekr")
    r = client.delete(f"{API}/vehicles/{owner.vehicle_id}", headers=owner.headers)
    assert r.status_code == 204, r.text
    body = {"type": "news", "target_vehicle_model_id": zeekr(client, admin), "message": "Нет"}
    assert preview(client, admin, **body) == {"recipients": 0, "devices": 0}


# ---------- Прошивки: таргетинг по версии (ADR 0019 п. 4) ----------


def set_firmware(client: TestClient, headers: Headers, vid: int, release_id: int):
    r = client.patch(
        f"{API}/vehicles/{vid}/firmware", json={"firmware_release_id": release_id}, headers=headers
    )
    return r


def test_firmware_release_targets_older_or_unknown_firmware(client, admin, make_owner, db: Session):
    model = zeekr(client, admin)
    unknown, older, newer = make_owner("Zeekr"), make_owner("Zeekr"), make_owner("Zeekr")
    other = make_owner("Voyah")
    v1 = release(client, admin, model, "1.0", date(2026, 1, 10)).json()
    v3 = release(client, admin, model, "3.0", date(2026, 9, 1)).json()
    assert (
        set_firmware(client, admin, older.vehicle_id, v1["id"]).json()["current_firmware_version"]
        == "1.0"
    )
    set_firmware(client, admin, newer.vehicle_id, v3["id"])

    r = release(client, admin, model, " 2.0 ", date(2026, 5, 1))
    assert r.status_code == 201, r.text
    v2 = r.json()
    assert v2["version"] == "2.0"
    items = feed(client, unknown.headers)["items"]
    assert items[0]["type"] == "firmware" and items[0]["firmware_release_id"] == v2["id"]
    assert items[0]["message"] == "Для Zeekr 001 доступна прошивка 2.0"
    assert feed(client, older.headers)["items"][0]["firmware_release_id"] == v2["id"]
    assert [n["firmware_release_id"] for n in feed(client, newer.headers)["items"]] == [
        v3["id"],
        v1["id"],
    ]
    assert feed(client, other.headers)["items"] == []

    # Та же дата выпуска: «раньше» — по id (ADR 0019 п. 4).
    same_day = release(client, admin, model, "2.0.1", date(2026, 5, 1)).json()
    set_firmware(client, admin, older.vehicle_id, v2["id"])
    assert feed(client, older.headers)["items"][0]["firmware_release_id"] == same_day["id"]

    r = client.get(
        f"{API}/firmware-releases", params={"vehicle_model_id": model}, headers=other.headers
    )
    assert r.status_code == 200
    assert [i["version"] for i in r.json()["items"]] == ["3.0", "2.0.1", "2.0", "1.0"]


def test_firmware_release_validation(client, admin):
    model = zeekr(client, admin)
    assert release(client, admin, model, "1.0", today_in_business_tz()).status_code == 201
    dup = release(client, admin, model, "1.0", date(2026, 1, 1))
    assert (dup.status_code, error_code(dup)) == (422, "FIRMWARE_VERSION_EXISTS")
    future = release(client, admin, model, "9.0", today_in_business_tz() + timedelta(days=1))
    assert (future.status_code, error_code(future)) == (422, "RELEASED_AT_IN_FUTURE")
    unknown = release(client, admin, 10**12, "1.0", date(2026, 1, 1))
    assert (unknown.status_code, error_code(unknown)) == (422, "VEHICLE_MODEL_NOT_FOUND")
    huge = release(client, admin, 2**63, "1.0", date(2026, 1, 1))
    assert huge.status_code == 422
    blank = release(client, admin, model, "   ", date(2026, 1, 1))
    assert blank.status_code == 422


def test_set_vehicle_firmware_access(client, admin, engineer, make_owner, make_ticket):
    owner = make_owner("Zeekr")
    other = make_owner("Voyah")
    zr = release(client, admin, zeekr(client, admin), "1.0", date(2026, 1, 1)).json()
    vr = release(client, admin, voyah(client, admin), "1.0", date(2026, 1, 1)).json()

    eng_headers, eng = engineer
    # Без тикета авто инженеру не видно (ADR 0014 п. 4).
    denied = set_firmware(client, eng_headers, owner.vehicle_id, zr["id"])
    assert denied.status_code == 404
    make_ticket(owner.vehicle_id, eng)
    assert set_firmware(client, eng_headers, owner.vehicle_id, zr["id"]).status_code == 200

    wrong_model = set_firmware(client, admin, owner.vehicle_id, vr["id"])
    assert (wrong_model.status_code, error_code(wrong_model)) == (422, "FIRMWARE_RELEASE_NOT_FOUND")
    assert set_firmware(client, admin, other.vehicle_id, 10**12).status_code == 422
    assert set_firmware(client, admin, 10**12, zr["id"]).status_code == 404
    r = client.patch(
        f"{API}/vehicles/{owner.vehicle_id}/firmware",
        json={"firmware_release_id": zr["id"]},
        headers=owner.headers,
    )
    assert r.status_code == 403


# ---------- Ручная публикация: проверки (ADR 0019 п. 4, 6, 11) ----------


@pytest.mark.parametrize(
    ("body", "code"),
    [
        ({"type": "maintenance", "message": "ТО"}, "NOTIFICATION_TYPE_RESERVED"),
        ({"type": "firmware", "message": "Прошивка"}, "FIRMWARE_RELEASE_REQUIRED"),
        (
            {"type": "firmware", "firmware_release_id": 10**12, "message": "Прошивка"},
            "FIRMWARE_RELEASE_NOT_FOUND",
        ),
        (
            {"type": "news", "target_vehicle_model_id": 10**12, "message": "Новость"},
            "VEHICLE_MODEL_NOT_FOUND",
        ),
        ({"type": "news", "message": "   "}, "VALIDATION_ERROR"),
        ({"type": "news", "message": "я" * 1001}, "VALIDATION_ERROR"),
        ({"type": "news", "message": "a\x00b"}, "VALIDATION_ERROR"),
        ({"type": "news", "message": "a\u009bb"}, "VALIDATION_ERROR"),
    ],
)
def test_create_notification_rejects(client, admin, body, code):
    for path, op in (
        ("/notifications", "createNotification"),
        ("/notifications/audience-preview", "previewNotificationAudience"),
    ):
        r = client.post(f"{API}{path}", json=body, headers=admin)
        assert (r.status_code, error_code(r)) == (422, code), path


def test_manual_firmware_notification_rules(client, admin, make_owner):
    owner = make_owner("Zeekr")
    model = zeekr(client, admin)
    fw = release(client, admin, model, "1.0", date(2026, 1, 1)).json()
    mismatch = client.post(
        f"{API}/notifications",
        json={
            "type": "firmware",
            "firmware_release_id": fw["id"],
            "target_vehicle_model_id": voyah(client, admin),
            "message": "Прошивка",
        },
        headers=admin,
    )
    assert (mismatch.status_code, error_code(mismatch)) == (422, "FIRMWARE_MODEL_MISMATCH")
    not_allowed = client.post(
        f"{API}/notifications",
        json={"type": "promo", "firmware_release_id": fw["id"], "message": "Акция"},
        headers=admin,
    )
    assert (not_allowed.status_code, error_code(not_allowed)) == (
        422,
        "FIRMWARE_RELEASE_NOT_ALLOWED",
    )
    # Модель не указана — берётся модель релиза; владелец без прошивки — в аудитории.
    manual = publish(
        client, admin, type="firmware", firmware_release_id=fw["id"], message="  Обновитесь\n"
    )
    assert manual["target_vehicle_model_id"] == model
    assert manual["message"] == "Обновитесь"
    assert feed(client, owner.headers)["items"][0]["id"] == manual["id"]


def test_message_is_nfc(client, admin, make_owner):
    owner = make_owner(None)
    decomposed = "\u0438\u0306"  # «й» в NFD — экранировано: исходники только в NFC
    publish(client, admin, type="news", message=f"Новости {decomposed}")
    text = feed(client, owner.headers)["items"][0]["message"]
    assert text == unicodedata.normalize("NFC", f"Новости {decomposed}")


# ---------- Push-токены (ADR 0019 п. 8) ----------


def active(db: Session, token: str) -> list[PushToken]:
    return list(
        db.scalars(
            select(PushToken).where(PushToken.token == token, PushToken.revoked_at.is_(None))
        )
    )


def test_push_token_lifecycle(client, as_client, db: Session):
    a = as_client("+375293390101")
    b = as_client("+375293390102")
    token = "shared-device:" + "t" * 150
    register(client, a, token)
    first = active(db, token)
    register(client, a, token)
    assert [t.id for t in active(db, token)] == [t.id for t in first], "свой токен не дублируется"

    register(client, b, token)  # сменили аккаунт на телефоне
    now = active(db, token)
    assert len(now) == 1 and now[0].id != first[0].id
    assert db.get(PushToken, first[0].id).revoked_at is not None

    r = client.delete(f"{API}/push-tokens/{token}", headers=a)
    assert r.status_code == 404
    r = client.delete(f"{API}/push-tokens/{token}", headers=b)
    assert r.status_code == 204
    assert active(db, token) == []
    assert client.delete(f"{API}/push-tokens/{token}", headers=b).status_code == 404

    too_long = client.post(f"{API}/push-tokens", json={"token": "x" * 1025}, headers=a)
    assert too_long.status_code == 422
    assert client.post(f"{API}/push-tokens", json={"token": ""}, headers=a).status_code == 422


def test_revoked_token_keeps_delivery_journal(client, admin, make_owner, db: Session):
    owner = make_owner(None)
    news = publish(client, admin, type="news", message="Журнал")
    r = client.delete(f"{API}/push-tokens/{owner.token}", headers=owner.headers)
    assert r.status_code == 204
    assert tokens_of(db, news["id"]) == {owner.token}, "строка доставки не удалена"


def test_consent_withdrawal_revokes_all_tokens(client, make_owner, db: Session):
    owner = make_owner(None)
    register(client, owner.headers, "second-device:" + "y" * 100)
    me = client.get(f"{API}/me", headers=owner.headers).json()["id"]
    assert client.delete(f"{API}/auth/pd-consent", headers=owner.headers).status_code == 202
    left = db.scalars(
        select(PushToken).where(PushToken.user_id == me, PushToken.revoked_at.is_(None))
    ).all()
    assert left == []


def test_push_tokens_client_only(client, admin, engineer):
    r = client.post(f"{API}/push-tokens", json={"token": "staff-token"}, headers=admin)
    assert r.status_code == 403
    r = client.post(f"{API}/push-tokens", json={"token": "staff-token"}, headers=engineer[0])
    assert r.status_code == 403
    assert client.post(f"{API}/push-tokens", json={"token": "t"}).status_code == 401


# ---------- Лента, прочтение и открытие (C-13, ADR 0019 п. 12) ----------


def test_feed_read_and_opened(client, admin, make_owner, make_worker, db: Session):
    owner = make_owner(None)
    stranger = make_owner(None)
    first = publish(client, admin, type="news", message="Первая")
    second = publish(client, admin, type="promo", message="Вторая")
    make_worker().dispatch()

    page = feed(client, owner.headers, page_size=1)
    assert [n["id"] for n in page["items"]] == [second["id"]]
    assert page["meta"]["total_items"] == 2 and page["meta"]["total_pages"] == 2
    assert page["items"][0]["read_at"] is None

    r = client.patch(f"{API}/notifications/{first['id']}/read", headers=owner.headers)
    assert r.status_code == 204
    read_at = feed(client, owner.headers)["items"][1]["read_at"]
    assert read_at is not None
    client.patch(f"{API}/notifications/{first['id']}/read", headers=owner.headers)
    assert feed(client, owner.headers)["items"][1]["read_at"] == read_at, "первое прочтение"

    r = client.post(
        f"{API}/notifications/{second['id']}/opened",
        json={"token": owner.token},
        headers=owner.headers,
    )
    assert r.status_code == 204
    delivery = db.scalars(
        select(NotificationDelivery)
        .where(NotificationDelivery.notification_id == second["id"])
        .join(PushToken, PushToken.id == NotificationDelivery.push_token_id)
        .where(PushToken.token == owner.token)
    ).one()
    assert delivery.opened_at is not None
    assert feed(client, owner.headers)["items"][0]["read_at"] is not None

    # Чужой токен открытие не пишет, но прочтение — да.
    third = publish(client, admin, type="news", message="Третья")
    r = client.post(
        f"{API}/notifications/{third['id']}/opened",
        json={"token": stranger.token},
        headers=owner.headers,
    )
    assert r.status_code == 204
    opened = db.scalars(
        select(NotificationDelivery.opened_at).where(
            NotificationDelivery.notification_id == third["id"]
        )
    ).all()
    assert opened == [None, None]

    for nid in (10**12, 2**63):
        r = client.patch(f"{API}/notifications/{nid}/read", headers=owner.headers)
        assert r.status_code == 404
    hidden = publish(
        client, admin, type="news", target_vehicle_model_id=zeekr(client, admin), message="Не вам"
    )
    r = client.patch(f"{API}/notifications/{hidden['id']}/read", headers=owner.headers)
    assert (r.status_code, error_code(r)) == (404, "NOTIFICATION_NOT_FOUND")
    r = client.post(
        f"{API}/notifications/{hidden['id']}/opened",
        json={"token": owner.token},
        headers=owner.headers,
    )
    assert r.status_code == 404


def test_feed_rbac(client, admin, engineer):
    assert client.get(f"{API}/notifications", headers=admin).status_code == 403
    assert client.get(f"{API}/notifications", headers=engineer[0]).status_code == 403
    r = client.post(
        f"{API}/notifications", json={"type": "news", "message": "x"}, headers=engineer[0]
    )
    assert r.status_code == 403


# ---------- Лента публикаций admin (ADR 0019 п. 12) ----------


def test_published_list_with_stats(client, admin, make_owner, make_worker, sender, db: Session):
    a, b = make_owner("Zeekr"), make_owner("Zeekr")
    make_owner("Voyah")
    news = publish(
        client, admin, type="news", target_vehicle_model_id=zeekr(client, admin), message="N"
    )
    promo = publish(client, admin, type="promo", message="P")
    sender.outcomes[b.token] = PushResult(Outcome.INVALID_TOKEN, "UNREGISTERED")
    make_worker().dispatch()
    client.post(
        f"{API}/notifications/{news['id']}/opened", json={"token": a.token}, headers=a.headers
    )

    r = client.get(f"{API}/notifications/published", headers=admin)
    assert r.status_code == 200, r.text
    items = {i["id"]: i for i in r.json()["items"]}
    assert list(items) == [promo["id"], news["id"]]
    assert items[news["id"]]["stats"] == {
        "recipients": 2,
        "delivered": 1,
        "failed": 1,
        "opened": 1,
        "read": 1,
    }
    assert items[promo["id"]]["stats"]["recipients"] == 3

    r = client.get(f"{API}/notifications/published", params={"type": "news"}, headers=admin)
    assert [i["id"] for i in r.json()["items"]] == [news["id"]]
    r = client.get(
        f"{API}/notifications/published",
        params={"target_vehicle_model_id": voyah(client, admin)},
        headers=admin,
    )
    assert r.json()["items"] == []
    r = client.get(f"{API}/notifications/published", params={"type": "maintenance"}, headers=admin)
    assert r.status_code == 422
    assert client.get(f"{API}/notifications/published", headers=a.headers).status_code == 403


# ---------- Пороги напоминания (N-10, ADR 0019 п. 5) ----------


def test_thresholds_reminder_fields(client, admin):
    r = client.get(f"{API}/aggregate-status-thresholds", headers=admin)
    assert (r.json()["reminder_before_km"], r.json()["reminder_before_days"]) == (1000, 14)

    body = {"yellow_from_percent": 70, "red_above_percent": 100}
    r = client.put(
        f"{API}/aggregate-status-thresholds",
        json=body | {"reminder_before_km": 500, "reminder_before_days": 7},
        headers=admin,
    )
    assert (r.json()["reminder_before_km"], r.json()["reminder_before_days"]) == (500, 7)
    r = client.put(f"{API}/aggregate-status-thresholds", json=body, headers=admin)
    assert (r.json()["reminder_before_km"], r.json()["reminder_before_days"]) == (500, 7)
    for bad in ({"reminder_before_km": 0}, {"reminder_before_days": 366}):
        r = client.put(f"{API}/aggregate-status-thresholds", json=body | bad, headers=admin)
        assert r.status_code == 422


def test_withdrawn_user_excluded_from_new_publications(client, admin, make_owner, db: Session):
    owner = make_owner(None)
    me = client.get(f"{API}/me", headers=owner.headers).json()["id"]
    db.execute(
        PdConsent.__table__.update()
        .where(PdConsent.user_id == me)
        .values(withdrawn_at=datetime.now(UTC))
    )
    assert preview(client, admin, type="news", message="x") == {"recipients": 0, "devices": 0}
