"""Пороги «светофора» (Глава 5, ADR 0009): одна строка 70/100, проверки, защита от удаления."""

import pytest
from sqlalchemy import Connection, text

from tests.db.factories import assert_violation, make_user, scalar

UPDATE = "UPDATE aggregate_status_thresholds SET yellow_from_percent = :y, red_above_percent = :r"


def test_seed_row_has_defaults(conn: Connection) -> None:
    rows = conn.execute(
        text(
            "SELECT id, yellow_from_percent, red_above_percent, updated_by_user_id "
            "FROM aggregate_status_thresholds"
        )
    ).all()
    assert [tuple(r) for r in rows] == [(1, 70, 100, None)]


def test_admin_update_bumps_updated_at(conn: Connection) -> None:
    admin = make_user(conn, "admin")
    conn.execute(
        text(
            "UPDATE aggregate_status_thresholds SET yellow_from_percent = 60, "
            "red_above_percent = 90, updated_by_user_id = :u, "
            "updated_at = TIMESTAMPTZ '2000-01-01'"
        ),
        {"u": admin},
    )
    row = conn.execute(
        text(
            "SELECT yellow_from_percent, red_above_percent, updated_by_user_id, "
            "updated_at = now() AS bumped FROM aggregate_status_thresholds"
        )
    ).one()
    assert tuple(row) == (60, 90, admin, True)


@pytest.mark.parametrize(
    ("yellow", "red"),
    [(0, 100), (70, 70), (90, 80), (70, 201)],
)
def test_percent_order_enforced(conn: Connection, yellow: int, red: int) -> None:
    assert_violation(conn, "ck_aggregate_status_thresholds_percent_order", UPDATE, y=yellow, r=red)


@pytest.mark.parametrize(("yellow", "red"), [(1, 2), (199, 200)])
def test_percent_bounds_inclusive(conn: Connection, yellow: int, red: int) -> None:
    conn.execute(text(UPDATE), {"y": yellow, "r": red})
    assert scalar(conn, "SELECT red_above_percent FROM aggregate_status_thresholds") == red


def test_second_row_rejected(conn: Connection) -> None:
    assert_violation(
        conn,
        "ck_aggregate_status_thresholds_singleton",
        "INSERT INTO aggregate_status_thresholds (id) VALUES (2)",
    )
    assert_violation(
        conn,
        "pk_aggregate_status_thresholds",
        "INSERT INTO aggregate_status_thresholds (id) VALUES (1)",
    )


def test_row_cannot_be_deleted(conn: Connection) -> None:
    assert_violation(
        conn,
        "aggregate_status_thresholds_singleton",
        "DELETE FROM aggregate_status_thresholds",
    )
