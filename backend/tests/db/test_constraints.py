"""Ограничения и инварианты схемы (Глава 2, MASTER_CHECKLIST «Проверка и тестирование»)."""

import pytest
from sqlalchemy import Connection, text

from tests.db.factories import (
    aggregate_type_id,
    assert_violation,
    fake_phone,
    fake_vin,
    make_firmware,
    make_model,
    make_ticket,
    make_user,
    make_vehicle,
    scalar,
)

# --- VIN -------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "vin",
    [
        "wvwzzz00000000001",  # строчные
        "WVWZZZI0000000001",  # I запрещена
        "WVWZZZO0000000001",  # O запрещена
        "WVWZZZ0000000001",  # 16 символов (CHAR(17) добивает пробелом)
    ],
)
def test_vin_format_rejected(conn: Connection, vin: str) -> None:
    user, model = make_user(conn), make_model(conn)
    assert_violation(
        conn,
        "ck_vehicle_vin_format",
        "INSERT INTO vehicle (user_id, vehicle_model_id, vin) VALUES (:u, :m, :v)",
        u=user,
        m=model,
        v=vin,
    )


def test_vin_unique_among_active_vehicles(conn: Connection) -> None:
    vin = fake_vin()
    make_vehicle(conn, vin=vin)
    assert_violation(
        conn,
        "uq_vehicle_vin_active",
        "INSERT INTO vehicle (user_id, vehicle_model_id, vin) VALUES (:u, :m, :v)",
        u=make_user(conn),
        m=make_model(conn),
        v=vin,
    )


def test_owner_change_keeps_maintenance_history(conn: Connection) -> None:
    """«Смена VIN/владельца не ломает историю ТО»: история привязана к vehicle.id."""
    vin, model = fake_vin(), make_model(conn)
    old = make_vehicle(conn, model_id=model, vin=vin, mileage=10_000)
    conn.execute(
        text(
            "INSERT INTO maintenance_record (vehicle_id, aggregate_type_id, performed_at, "
            "mileage_at_service) VALUES (:v, :a, DATE '2026-05-01', 10000)"
        ),
        {"v": old, "a": aggregate_type_id(conn)},
    )
    conn.execute(text("UPDATE vehicle SET deleted_at = now() WHERE id = :v"), {"v": old})
    new = make_vehicle(conn, model_id=model, vin=vin, mileage=10_000)

    assert new != old
    history = "SELECT count(*) FROM maintenance_record WHERE vehicle_id = :v"
    assert scalar(conn, history, v=old) == 1
    assert scalar(conn, history, v=new) == 0  # новый владелец не видит чужую историю


@pytest.mark.parametrize(
    ("column", "value_sql"),
    [
        ("vin", "'WVWZZZ99999999999'"),
        ("user_id", "(SELECT max(id) FROM app_user)"),
        ("vehicle_model_id", "(SELECT max(id) FROM vehicle_model)"),
    ],
)
def test_vehicle_identity_is_immutable(conn: Connection, column: str, value_sql: str) -> None:
    vehicle = make_vehicle(conn)
    make_user(conn)
    make_model(conn)
    assert_violation(
        conn,
        "vehicle_identity_immutable",
        f"UPDATE vehicle SET {column} = {value_sql} WHERE id = :v",
        v=vehicle,
    )


# --- Пробег ---------------------------------------------------------------------------


def test_mileage_cannot_be_negative(conn: Connection) -> None:
    assert_violation(
        conn,
        "ck_vehicle_mileage_non_negative",
        "INSERT INTO vehicle (user_id, vehicle_model_id, vin, mileage) VALUES (:u, :m, :v, -1)",
        u=make_user(conn),
        m=make_model(conn),
        v=fake_vin(),
    )


def test_mileage_cannot_decrease(conn: Connection) -> None:
    vehicle = make_vehicle(conn, mileage=50_000)
    assert_violation(
        conn,
        "vehicle_mileage_monotonic",
        "UPDATE vehicle SET mileage = 49999 WHERE id = :v",
        v=vehicle,
    )


def test_conditional_mileage_update_reports_conflict(conn: Connection) -> None:
    """Паттерн сервисного слоя: 0 строк = 409 без ошибки триггера."""
    vehicle = make_vehicle(conn, mileage=50_000)
    update = text("UPDATE vehicle SET mileage = :km WHERE id = :v AND mileage <= :km RETURNING id")
    assert conn.execute(update, {"v": vehicle, "km": 40_000}).all() == []
    assert conn.execute(update, {"v": vehicle, "km": 50_000}).all() == [(vehicle,)]
    assert conn.execute(update, {"v": vehicle, "km": 60_000}).all() == [(vehicle,)]


# --- Пользователь ----------------------------------------------------------------------


@pytest.mark.parametrize("phone", ["375291234567", "+0291234567", "+375 29 1234", "+123456"])
def test_phone_must_be_e164(conn: Connection, phone: str) -> None:
    assert_violation(
        conn,
        "ck_app_user_phone_e164",
        "INSERT INTO app_user (phone, role) VALUES (:p, 'client')",
        p=phone,
    )


def test_phone_unique(conn: Connection) -> None:
    phone = fake_phone()
    make_user(conn, phone=phone)
    assert_violation(
        conn,
        "uq_app_user_phone",
        "INSERT INTO app_user (phone, role) VALUES (:p, 'client')",
        p=phone,
    )


def test_phone_required_unless_anonymized(conn: Connection) -> None:
    assert_violation(
        conn, "ck_app_user_phone_required", "INSERT INTO app_user (role) VALUES ('client')"
    )
    conn.execute(text("INSERT INTO app_user (role, anonymized_at) VALUES ('client', now())"))


@pytest.mark.parametrize("role", ["engineer", "admin"])
def test_staff_requires_password_hash(conn: Connection, role: str) -> None:
    assert_violation(
        conn,
        "ck_app_user_staff_password",
        "INSERT INTO app_user (phone, role) VALUES (:p, :r)",
        p=fake_phone(),
        r=role,
    )


def test_pd_consent_requires_policy_version(conn: Connection) -> None:
    assert_violation(
        conn,
        "ck_app_user_pd_consent_pair",
        "INSERT INTO app_user (phone, role, pd_consent_at) VALUES (:p, 'client', now())",
        p=fake_phone(),
    )


def test_refresh_token_stores_only_sha256(conn: Connection) -> None:
    assert_violation(
        conn,
        "ck_refresh_token_token_hash_sha256",
        "INSERT INTO refresh_token (user_id, token_hash, expires_at) "
        "VALUES (:u, 'plain-refresh-token', now() + interval '30 days')",
        u=make_user(conn),
    )


# --- Агрегаты и регламенты ---------------------------------------------------------


def test_one_status_per_vehicle_and_aggregate(conn: Connection) -> None:
    vehicle, agg = make_vehicle(conn), aggregate_type_id(conn)
    insert = "INSERT INTO vehicle_aggregate_status (vehicle_id, aggregate_type_id) VALUES (:v, :a)"
    conn.execute(text(insert), {"v": vehicle, "a": agg})
    assert_violation(
        conn, "uq_vehicle_aggregate_status_vehicle_id_aggregate_type_id", insert, v=vehicle, a=agg
    )


def test_regulation_interval_rules(conn: Connection) -> None:
    model, agg = make_model(conn), aggregate_type_id(conn)
    insert = (
        "INSERT INTO maintenance_regulation (vehicle_model_id, aggregate_type_id, interval_km, "
        "interval_months, is_archived) VALUES (:m, :a, :km, :mon, :arch)"
    )
    base = {"m": model, "a": agg, "arch": False}
    assert_violation(
        conn, "ck_maintenance_regulation_interval_present", insert, km=None, mon=None, **base
    )
    assert_violation(
        conn, "ck_maintenance_regulation_interval_km_positive", insert, km=0, mon=None, **base
    )
    assert_violation(
        conn, "ck_maintenance_regulation_interval_months_positive", insert, km=None, mon=0, **base
    )
    conn.execute(text(insert), {**base, "km": 10_000, "mon": 12, "arch": True})
    conn.execute(text(insert), {**base, "km": 15_000, "mon": 12})
    assert_violation(conn, "uq_maintenance_regulation_active", insert, km=20_000, mon=None, **base)


# --- База знаний -----------------------------------------------------------------------


def test_decision_tree_single_root_and_array_options(conn: Connection) -> None:
    article = scalar(
        conn,
        "INSERT INTO knowledge_article (article_type, title) "
        "VALUES ('troubleshooting', 'Нет звука') RETURNING id",
    )
    insert = (
        "INSERT INTO decision_tree_node (article_id, question_text, is_root, options) "
        "VALUES (:a, 'Вопрос', :root, CAST(:opts AS jsonb))"
    )
    conn.execute(text(insert), {"a": article, "root": True, "opts": "[]"})
    assert_violation(conn, "uq_decision_tree_node_root", insert, a=article, root=True, opts="[]")
    assert_violation(
        conn, "ck_decision_tree_node_options_is_array", insert, a=article, root=False, opts="{}"
    )


def test_article_firmware_must_match_model(conn: Connection) -> None:
    model_a, model_b = make_model(conn), make_model(conn)
    fw_b = make_firmware(conn, model_b)
    assert_violation(
        conn,
        "fk_knowledge_article_firmware_same_model",
        "INSERT INTO knowledge_article (article_type, title, vehicle_model_id, "
        "firmware_release_id) VALUES ('guide', 'Руководство', :m, :f)",
        m=model_a,
        f=fw_b,
    )


# --- Тикеты и вложения ----------------------------------------------------------------


def test_resolved_status_requires_resolved_at(conn: Connection) -> None:
    ticket = make_ticket(conn)
    assert_violation(
        conn,
        "ck_ticket_resolved_at_consistent",
        "UPDATE ticket SET status = 'resolved' WHERE id = :t",
        t=ticket,
    )
    conn.execute(
        text("UPDATE ticket SET status = 'resolved', resolved_at = now() WHERE id = :t"),
        {"t": ticket},
    )


def test_attachment_message_must_belong_to_same_ticket(conn: Connection) -> None:
    vehicle = make_vehicle(conn)
    author = scalar(conn, "SELECT user_id FROM vehicle WHERE id = :v", v=vehicle)
    ticket_a, ticket_b = make_ticket(conn, vehicle), make_ticket(conn, vehicle)
    message_b = scalar(
        conn,
        "INSERT INTO ticket_message (ticket_id, author_id, body) VALUES (:t, :u, 'фото') "
        "RETURNING id",
        t=ticket_b,
        u=author,
    )
    insert = (
        "INSERT INTO ticket_attachment (ticket_id, ticket_message_id, object_key, file_type, "
        "mime_type, size_bytes, uploaded_by_user_id) "
        "VALUES (:t, :msg, :key, :ft, :mime, 1024, :u)"
    )
    assert_violation(
        conn,
        "fk_ticket_attachment_message_same_ticket",
        insert,
        t=ticket_a,
        msg=message_b,
        key="tickets/a/1.jpg",
        ft="photo",
        mime="image/jpeg",
        u=author,
    )
    assert_violation(
        conn,
        "ck_ticket_attachment_mime_matches_type",
        insert,
        t=ticket_b,
        msg=message_b,
        key="tickets/b/1.mp4",
        ft="photo",
        mime="video/mp4",
        u=author,
    )


def test_vehicle_firmware_must_match_model(conn: Connection) -> None:
    vehicle = make_vehicle(conn)
    foreign_fw = make_firmware(conn, make_model(conn))
    assert_violation(
        conn,
        "fk_vehicle_firmware_same_model",
        "UPDATE vehicle SET current_firmware_release_id = :f WHERE id = :v",
        f=foreign_fw,
        v=vehicle,
    )


# --- Уведомления ----------------------------------------------------------------------


def test_firmware_notification_requires_release(conn: Connection) -> None:
    assert_violation(
        conn,
        "ck_notification_firmware_has_release",
        "INSERT INTO notification (type, message) VALUES ('firmware', 'Новая прошивка')",
    )


def test_notification_read_state_is_per_user(conn: Connection) -> None:
    user = make_user(conn)
    notification = scalar(
        conn, "INSERT INTO notification (type, message) VALUES ('news', 'Новость') RETURNING id"
    )
    insert = "INSERT INTO notification_recipient (notification_id, user_id) VALUES (:n, :u)"
    conn.execute(text(insert), {"n": notification, "u": user})
    assert_violation(
        conn, "uq_notification_recipient_notification_id_user_id", insert, n=notification, u=user
    )


# --- ON DELETE ---------------------------------------------------------------------------


def test_user_with_vehicle_cannot_be_hard_deleted(conn: Connection) -> None:
    vehicle = make_vehicle(conn)
    user = scalar(conn, "SELECT user_id FROM vehicle WHERE id = :v", v=vehicle)
    assert_violation(
        conn, "fk_vehicle_user_id_app_user", "DELETE FROM app_user WHERE id = :u", u=user
    )


def test_technical_rows_cascade_with_user(conn: Connection) -> None:
    user = make_user(conn)
    conn.execute(
        text("INSERT INTO push_token (user_id, token) VALUES (:u, :t)"), {"u": user, "t": "tok-1"}
    )
    conn.execute(text("DELETE FROM app_user WHERE id = :u"), {"u": user})
    assert scalar(conn, "SELECT count(*) FROM push_token WHERE user_id = :u", u=user) == 0


# --- RBAC-01: схема позволяет object-level проверку ---------------------------------------


def test_rbac01_engineer_vehicle_access_via_assigned_ticket(conn: Connection) -> None:
    engineer, other = make_user(conn, "engineer"), make_user(conn, "engineer")
    vehicle = make_vehicle(conn)
    make_ticket(conn, vehicle, assigned_engineer_id=engineer)
    can_edit = (
        "SELECT EXISTS (SELECT 1 FROM ticket WHERE vehicle_id = :v AND assigned_engineer_id = :e)"
    )
    assert scalar(conn, can_edit, v=vehicle, e=engineer) is True
    assert scalar(conn, can_edit, v=vehicle, e=other) is False
