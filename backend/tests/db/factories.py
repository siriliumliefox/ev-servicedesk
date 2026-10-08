"""Минимальные SQL-фабрики тестовых данных. Телефоны и VIN — синтетические."""

import itertools

import pytest
from sqlalchemy import Connection, text
from sqlalchemy.exc import DBAPIError

_seq = itertools.count(1)


def _n() -> int:
    return next(_seq)


def fake_phone() -> str:
    return f"+37500{_n():07d}"


def fake_vin() -> str:
    # Только допустимые символы VIN (без I, O, Q).
    return f"WVWZZZ{_n():011d}"


def scalar(conn: Connection, sql: str, **params):
    return conn.execute(text(sql), params).scalar_one()


def make_user(conn: Connection, role: str = "client", phone: str | None = None) -> int:
    password_hash = None if role == "client" else "$argon2id$test-only"
    return scalar(
        conn,
        "INSERT INTO app_user (phone, role, password_hash) VALUES (:p, :r, :h) RETURNING id",
        p=phone or fake_phone(),
        r=role,
        h=password_hash,
    )


def make_model(conn: Connection) -> int:
    n = _n()
    return scalar(
        conn,
        "INSERT INTO vehicle_model (brand, model) VALUES (:b, :m) RETURNING id",
        b=f"TestBrand{n}",
        m=f"Model{n}",
    )


def make_firmware(conn: Connection, model_id: int, version: str | None = None) -> int:
    return scalar(
        conn,
        "INSERT INTO firmware_release (vehicle_model_id, version, released_at) "
        "VALUES (:m, :v, DATE '2026-01-01') RETURNING id",
        m=model_id,
        v=version or f"1.0.{_n()}",
    )


def make_vehicle(
    conn: Connection,
    user_id: int | None = None,
    model_id: int | None = None,
    vin: str | None = None,
    mileage: int = 0,
) -> int:
    return scalar(
        conn,
        "INSERT INTO vehicle (user_id, vehicle_model_id, vin, mileage) "
        "VALUES (:u, :m, :vin, :km) RETURNING id",
        u=user_id or make_user(conn),
        m=model_id or make_model(conn),
        vin=vin or fake_vin(),
        km=mileage,
    )


def make_ticket(conn: Connection, vehicle_id: int | None = None, **cols) -> int:
    values = {
        "vehicle_id": vehicle_id or make_vehicle(conn),
        "category": "navigation",
        "description": "Не работает навигация",
        **cols,
    }
    names = ", ".join(values)
    binds = ", ".join(f":{k}" for k in values)
    return scalar(
        conn,
        f"INSERT INTO ticket ({names}, sla_due_at) VALUES ({binds}, now() + interval '15 minutes') "
        "RETURNING id",
        **values,
    )


def aggregate_type_id(conn: Connection, code: str = "engine_oil") -> int:
    return scalar(conn, "SELECT id FROM aggregate_type WHERE code = :c", c=code)


def assert_violation(conn: Connection, constraint: str, sql: str, **params) -> None:
    """Выполняет SQL в savepoint и проверяет, что сработало именно указанное ограничение."""
    savepoint = conn.begin_nested()
    with pytest.raises(DBAPIError) as exc_info:
        conn.execute(text(sql), params)
    savepoint.rollback()
    actual = exc_info.value.orig.diag.constraint_name
    assert actual == constraint, f"ожидалось {constraint}, сработало {actual}"
