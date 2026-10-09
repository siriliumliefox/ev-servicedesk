"""Техдолг главы 2 (#15, ADR 0006): корректировка пробега, updated_at в БД, согласия ПД."""

import pytest
from sqlalchemy import Connection, text

from app.models import Base
from tests.db.factories import assert_violation, make_user, make_vehicle, scalar

CORRECT = (
    "INSERT INTO vehicle_mileage_correction "
    "(vehicle_id, corrected_by_user_id, old_mileage, new_mileage, reason) "
    "VALUES (:v, :u, :old, :new, :reason) RETURNING id"
)

# --- Корректировка пробега -------------------------------------------------------------


def test_admin_correction_lowers_mileage_with_audit(conn: Connection) -> None:
    admin, vehicle = make_user(conn, "admin"), make_vehicle(conn, mileage=150_000)
    correction = scalar(
        conn, CORRECT, v=vehicle, u=admin, old=150_000, new=15_000, reason="Опечатка: лишний ноль"
    )
    assert scalar(conn, "SELECT mileage FROM vehicle WHERE id = :v", v=vehicle) == 15_000
    row = conn.execute(
        text(
            "SELECT old_mileage, new_mileage, corrected_by_user_id FROM vehicle_mileage_correction "
            "WHERE id = :c"
        ),
        {"c": correction},
    ).one()
    assert tuple(row) == (150_000, 15_000, admin)


@pytest.mark.parametrize("role", ["client", "engineer"])
def test_only_admin_can_correct(conn: Connection, role: str) -> None:
    actor, vehicle = make_user(conn, role), make_vehicle(conn, mileage=100)
    assert_violation(
        conn,
        "mileage_correction_admin_only",
        CORRECT,
        v=vehicle,
        u=actor,
        old=100,
        new=10,
        reason="x",
    )


def test_stale_correction_rejected(conn: Connection) -> None:
    admin, vehicle = make_user(conn, "admin"), make_vehicle(conn, mileage=500)
    assert_violation(
        conn, "mileage_correction_stale", CORRECT, v=vehicle, u=admin, old=400, new=10, reason="x"
    )


@pytest.mark.parametrize(
    ("new", "reason", "constraint"),
    [
        (600, "x", "ck_vehicle_mileage_correction_decrease_only"),
        (-1, "x", "ck_vehicle_mileage_correction_new_mileage_non_negative"),
        (10, "   ", "ck_vehicle_mileage_correction_reason_not_blank"),
    ],
)
def test_correction_checks(conn: Connection, new: int, reason: str, constraint: str) -> None:
    admin, vehicle = make_user(conn, "admin"), make_vehicle(conn, mileage=500)
    assert_violation(conn, constraint, CORRECT, v=vehicle, u=admin, old=500, new=new, reason=reason)


@pytest.mark.parametrize(
    "sql",
    [
        "UPDATE vehicle_mileage_correction SET reason = 'changed' WHERE id = :c",
        "DELETE FROM vehicle_mileage_correction WHERE id = :c",
    ],
)
def test_correction_log_is_append_only(conn: Connection, sql: str) -> None:
    admin, vehicle = make_user(conn, "admin"), make_vehicle(conn, mileage=500)
    correction = scalar(conn, CORRECT, v=vehicle, u=admin, old=500, new=50, reason="ошибка")
    assert_violation(conn, "vehicle_mileage_correction_append_only", sql, c=correction)


def test_direct_decrease_still_forbidden_even_for_admin(conn: Connection) -> None:
    vehicle = make_vehicle(conn, mileage=500)
    assert_violation(
        conn,
        "vehicle_mileage_monotonic",
        "UPDATE vehicle SET mileage = 50 WHERE id = :v",
        v=vehicle,
    )


# --- updated_at --------------------------------------------------------------------------


def test_every_updated_at_table_has_trigger(conn: Connection) -> None:
    expected = {name for name, t in Base.metadata.tables.items() if "updated_at" in t.c}
    actual = set(
        conn.execute(
            text(
                "SELECT c.relname FROM pg_trigger t JOIN pg_class c ON c.oid = t.tgrelid "
                "WHERE t.tgname = 'trg_set_updated_at' AND NOT t.tgisinternal"
            )
        ).scalars()
    )
    assert actual == expected


def test_raw_sql_update_bumps_updated_at(conn: Connection) -> None:
    user = make_user(conn)
    conn.execute(
        text("UPDATE app_user SET updated_at = TIMESTAMPTZ '2000-01-01' WHERE id = :u"), {"u": user}
    )
    # Триггер перезаписывает даже явно переданное значение — источник истины БД.
    assert scalar(conn, "SELECT updated_at = now() FROM app_user WHERE id = :u", u=user) is True


# --- Согласия ПД (99-З, ст. 5, 10) ---------------------------------------------------------

CONSENT = "INSERT INTO pd_consent (user_id, policy_version) VALUES (:u, :v) RETURNING id"


def test_single_active_consent_and_history(conn: Connection) -> None:
    user = make_user(conn)
    first = scalar(conn, CONSENT, u=user, v="2026-10")
    assert_violation(conn, "uq_pd_consent_active", CONSENT, u=user, v="2026-11")
    conn.execute(text("UPDATE pd_consent SET withdrawn_at = now() WHERE id = :c"), {"c": first})
    scalar(conn, CONSENT, u=user, v="2026-11")  # повторное согласие после отзыва
    assert scalar(conn, "SELECT count(*) FROM pd_consent WHERE user_id = :u", u=user) == 2


def test_consent_checks(conn: Connection) -> None:
    user = make_user(conn)
    assert_violation(conn, "ck_pd_consent_policy_version_not_blank", CONSENT, u=user, v=" ")
    assert_violation(
        conn,
        "ck_pd_consent_withdrawn_after_given",
        "INSERT INTO pd_consent (user_id, policy_version, given_at, withdrawn_at) "
        "VALUES (:u, 'v1', now(), now() - interval '1 day')",
        u=user,
    )


def test_consent_survives_user_anonymization(conn: Connection) -> None:
    """Доказательство согласия и его отзыва хранится после удаления ПД (анонимизации)."""
    user = make_user(conn)
    consent = scalar(conn, CONSENT, u=user, v="2026-10")
    conn.execute(text("UPDATE pd_consent SET withdrawn_at = now() WHERE id = :c"), {"c": consent})
    conn.execute(
        text("UPDATE app_user SET phone = NULL, anonymized_at = now() WHERE id = :u"), {"u": user}
    )
    assert scalar(conn, "SELECT count(*) FROM pd_consent WHERE user_id = :u", u=user) == 1
    assert_violation(
        conn, "fk_pd_consent_user_id_app_user", "DELETE FROM app_user WHERE id = :u", u=user
    )


@pytest.mark.parametrize(
    "sql",
    [
        "UPDATE pd_consent SET policy_version = 'forged' WHERE id = :c",
        "UPDATE pd_consent SET given_at = now() - interval '1 year' WHERE id = :c",
        "DELETE FROM pd_consent WHERE id = :c",
    ],
)
def test_consent_evidence_is_immutable(conn: Connection, sql: str) -> None:
    consent = scalar(conn, CONSENT, u=make_user(conn), v="2026-10")
    assert_violation(conn, "pd_consent_withdraw_only", sql, c=consent)


def test_consent_withdrawal_is_final(conn: Connection) -> None:
    consent = scalar(conn, CONSENT, u=make_user(conn), v="2026-10")
    conn.execute(text("UPDATE pd_consent SET withdrawn_at = now() WHERE id = :c"), {"c": consent})
    assert scalar(conn, "SELECT updated_at = now() FROM pd_consent WHERE id = :c", c=consent)
    assert_violation(
        conn,
        "pd_consent_withdraw_only",
        "UPDATE pd_consent SET withdrawn_at = NULL WHERE id = :c",
        c=consent,
    )
