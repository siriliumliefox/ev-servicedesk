"""Нормативы SLA (Глава 13, ADR 0017 п. 1–2): срок решения по категории, seed — миграция 0008."""

import pytest
from sqlalchemy import Connection, select, text
from sqlalchemy.orm import Session

from app.models import TicketSlaPolicy
from app.models.enums import TicketCategory
from tests.db.factories import assert_violation, scalar

APPROVED_MINUTES = {
    TicketCategory.APP_CRASH: 4 * 60,
    TicketCategory.NAVIGATION: 8 * 60,
    TicketCategory.SIM: 8 * 60,
    TicketCategory.AUDIO: 24 * 60,
    TicketCategory.MAINTENANCE: 48 * 60,
}


def test_seed_covers_every_category(conn: Connection) -> None:
    """Норматив есть у каждой категории: иначе тикет этой категории не создать."""
    rows = conn.execute(text("SELECT category, resolution_minutes FROM ticket_sla_policy")).all()
    assert {TicketCategory(r.category): r.resolution_minutes for r in rows} == APPROVED_MINUTES
    assert set(APPROVED_MINUTES) == set(TicketCategory)


def test_orm_reads_policy_by_category(conn: Connection) -> None:
    with Session(bind=conn) as session:
        policies = session.scalars(select(TicketSlaPolicy)).all()
        assert {p.category: p.resolution_minutes for p in policies} == APPROVED_MINUTES
        assert session.get(TicketSlaPolicy, TicketCategory.APP_CRASH).resolution_minutes == 240


@pytest.mark.parametrize("minutes", [0, -60])
def test_resolution_minutes_must_be_positive(conn: Connection, minutes: int) -> None:
    assert_violation(
        conn,
        "ck_ticket_sla_policy_resolution_minutes_positive",
        "UPDATE ticket_sla_policy SET resolution_minutes = :m WHERE category = 'sim'",
        m=minutes,
    )


def test_one_policy_per_category(conn: Connection) -> None:
    assert_violation(
        conn,
        "pk_ticket_sla_policy",
        "INSERT INTO ticket_sla_policy (category, resolution_minutes) VALUES ('audio', 60)",
    )


def test_update_bumps_updated_at(conn: Connection) -> None:
    conn.execute(
        text(
            "UPDATE ticket_sla_policy SET resolution_minutes = 300, "
            "updated_at = TIMESTAMPTZ '2000-01-01' WHERE category = 'app_crash'"
        )
    )
    assert scalar(
        conn,
        "SELECT updated_at = now() FROM ticket_sla_policy WHERE category = 'app_crash'",
    )
