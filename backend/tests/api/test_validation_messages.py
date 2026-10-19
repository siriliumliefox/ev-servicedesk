"""Тексты ошибок валидации схемы — по-русски (#105, №15, ADR 0034).

Клиенты показывают свои тексты по коду и полю (`details.fields[].loc`), но `msg` видят разработчики
интеграций и поддержка: вместо «Input should be…» и «Field required» — русский текст по типу ошибки
Pydantic, у своих проверок — их текст без префикса «Value error, ». Введённое значение в текст не
попадает.
"""

import pytest

from app.core.errors import validation_message
from tests.api.conftest import API, Headers, add_vehicle
from tests.api.ticket_support import create

ENGLISH = ("Input should", "Field required", "Value error", "Assertion failed", " or ", "valid")


@pytest.fixture
def owner(as_client) -> Headers:
    return as_client("+375293300201")


def fields(response) -> dict[str, str]:
    assert response.status_code == 422, response.text
    body = response.json()["error"]
    assert body["code"] == "VALIDATION_ERROR"
    return {e["loc"][-1]: e["msg"] for e in body["details"]["fields"]}


def test_schema_errors_are_russian(client, owner):
    vehicle = add_vehicle(client, owner)
    r = client.post(
        f"{API}/tickets",
        json={"vehicle_id": "сорок два", "category": "radio", "client_request_id": "черновик-1"},
        headers=owner,
    )
    texts = fields(r)
    assert texts == {
        "vehicle_id": "Нужно целое число",
        "category": "Допустимые значения: 'navigation', 'audio', 'sim', 'app_crash', 'maintenance'",
        "description": "Обязательное поле",
        "client_request_id": "Нужен UUID",
    }
    tid = create(client, owner, vehicle["id"])["id"]
    r = client.post(f"{API}/tickets/{tid}/messages", json={"body": "   "}, headers=owner)
    assert fields(r) == {"body": "текст не может быть пустым"}, "своя проверка — без префикса"
    r = client.get(f"{API}/tickets", params={"page_size": 1000}, headers=owner)
    assert fields(r) == {"page_size": "Не больше 100"}
    for text in (*texts.values(), "Не больше 100"):
        assert not any(word in text for word in ENGLISH), text
        assert "сорок два" not in text and "черновик" not in text, "введённого значения нет"


@pytest.mark.parametrize(
    ("error", "text"),
    [
        ({"type": "string_too_long", "msg": "", "ctx": {"max_length": 5}}, "Не длиннее 5 символов"),
        ({"type": "greater_than_equal", "msg": "x", "ctx": {"ge": 500}}, "Не меньше 500"),
        ({"type": "value_error", "msg": "Value error, нужно yellow < red"}, "нужно yellow < red"),
        ({"type": "unknown_type", "msg": "Something"}, "Недопустимое значение"),
        ({"type": "greater_than_equal", "msg": "x", "ctx": {}}, "Недопустимое значение"),
    ],
)
def test_validation_message(error, text):
    assert validation_message(error) == text
