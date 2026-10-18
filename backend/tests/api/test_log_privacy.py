"""Сквозное маскирование логов (99-З п. 2, ADR 0029 п. 17).

Сценарии всех сервисов с ПД во входных данных — телефон (в теле и строке поиска), VIN, SMS-код,
описание и сообщение тикета, push-токен (в пути), Telegram, пароль, access/refresh-токены — и все
логи на уровне DEBUG: ни одно значение не попадает в журнал даже до фильтра `PiiFilter` (первая
линия), журнал доступа пишет шаблон маршрута без строки запроса. Фильтр — вторая линия:
маскирует ПД, если они всё же попали в сообщение или трассировку.
"""

import logging

import pytest

from app.core.logging import PiiFilter, mask_pii
from app.models.enums import UserRole
from tests.api.conftest import (
    API,
    POLICY,
    STAFF_PASSWORD,
    ZEEKR_VIN,
    add_vehicle,
    bearer,
    code_from,
    telegram_widget,
)
from tests.api.ticket_support import create

CLIENT_PHONE = "+375296690001"
ADMIN_PHONE = "+375296690002"
DESCRIPTION = "Стучит подвеска возле дома на Советской 15"
MESSAGE = "Мой второй номер +375447770011, звоните вечером"
PUSH_TOKEN = "fcm-private-token:" + "z" * 40
TELEGRAM_ID = "5550001"


def test_no_personal_data_in_logs(client, sms, make_staff, caplog):
    caplog.set_level(logging.DEBUG)
    r = client.post(f"{API}/auth/phone/request-code", json={"phone": CLIENT_PHONE})
    assert r.status_code == 200
    code = code_from(sms, CLIENT_PHONE)
    wrong = client.post(
        f"{API}/auth/phone/verify-code", json={"phone": CLIENT_PHONE, "code": "0000"}
    )
    assert wrong.status_code == 400
    session = client.post(
        f"{API}/auth/phone/verify-code",
        json={"phone": CLIENT_PHONE, "code": code, "pd_policy_version": POLICY},
    ).json()
    owner = bearer(session["access_token"])

    vehicle = add_vehicle(client, owner, ZEEKR_VIN)
    assert client.post(f"{API}/vehicles", json={"vin": ZEEKR_VIN}, headers=owner).status_code == 409
    ticket = create(client, owner, vehicle["id"], category="sim", description=DESCRIPTION)
    r = client.post(f"{API}/tickets/{ticket['id']}/messages", json={"body": MESSAGE}, headers=owner)
    assert r.status_code in (201, 403)  # клиент пишет после взятия в работу — лог в обоих случаях
    assert (
        client.post(f"{API}/push-tokens", json={"token": PUSH_TOKEN}, headers=owner).status_code
        == 201
    )
    assert client.delete(f"{API}/push-tokens/{PUSH_TOKEN}", headers=owner).status_code == 204
    widget = telegram_widget(TELEGRAM_ID)
    assert client.post(f"{API}/auth/telegram/link", json=widget, headers=owner).status_code == 200

    make_staff(ADMIN_PHONE, UserRole.ADMIN)
    bad = client.post(
        f"{API}/auth/staff/login", json={"phone": ADMIN_PHONE, "password": "Wrong-Password-1"}
    )
    assert bad.status_code == 401
    admin = client.post(
        f"{API}/auth/staff/login", json={"phone": ADMIN_PHONE, "password": STAFF_PASSWORD}
    ).json()
    found = client.get(
        f"{API}/users", params={"search": CLIENT_PHONE}, headers=bearer(admin["access_token"])
    )
    assert found.status_code == 200 and found.json()["items"]
    r = client.post(
        f"{API}/auth/logout",
        json={"refresh_token": session["refresh_token"]},
        headers=owner,
    )
    assert r.status_code == 204

    # httpx на INFO — запросы самого TestClient (в API httpx — от WARNING, configure_logging).
    handler = logging.Formatter("%(name)s %(message)s")
    logs = "\n".join(
        handler.format(record) + (record.exc_text or "")
        for record in caplog.records
        if record.name != "httpx"
    )
    assert "app.access" in logs and f"GET {API}/users 200" in logs, "журнал доступа ведётся"
    assert f"DELETE {API}/push-tokens/{{token}} 204" in logs, "шаблон маршрута, а не значение"
    secrets = {
        "телефон клиента": CLIENT_PHONE,
        "телефон без плюса": CLIENT_PHONE[1:],
        "телефон администратора": ADMIN_PHONE,
        "VIN": ZEEKR_VIN,
        "SMS-код": f"код входа {code}",
        "описание тикета": DESCRIPTION,
        "сообщение": MESSAGE,
        "push-токен": PUSH_TOKEN,
        "Telegram": TELEGRAM_ID,
        "пароль": STAFF_PASSWORD,
        "неверный пароль": "Wrong-Password-1",
        "access-токен": session["access_token"],
        "refresh-токен": session["refresh_token"],
    }
    leaked = [name for name, value in secrets.items() if value in logs]
    assert not leaked, f"ПД в логах: {leaked}"


@pytest.mark.parametrize(
    ("raw", "masked"),
    [
        ("номер +375291234567", "номер +375*******67"),
        ("номер 375291234567", "номер 3752******67"),
        ("vin L6TZ0010000000001", "vin L6T**************"),
        ("Bearer eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiI3In0.c2lnbmF0dXJl", "Bearer <jwt>"),
        ("тикет 123, статус resolved", "тикет 123, статус resolved"),
    ],
)
def test_mask_pii(raw, masked):
    assert mask_pii(raw) == masked


def test_filter_masks_message_args_and_traceback():
    record = logging.LogRecord("x", logging.ERROR, __file__, 1, "вход %s", ("+375291234567",), None)
    try:
        raise ValueError("VIN L6TZ0010000000001 не найден")
    except ValueError:
        import sys

        record.exc_info = sys.exc_info()
    assert PiiFilter().filter(record)
    assert record.getMessage() == "вход +375*******67"
    assert "L6TZ0010000000001" not in record.exc_text and "L6T**************" in record.exc_text
