"""SLA — срок решения тикета (ADR 0017 п. 1–3): чистые функции и нормативы миграции 0008."""

from datetime import UTC, datetime, timedelta

import pytest

from app.domain.tickets.sla import due_at, is_overdue
from app.models.enums import TicketStatus

CREATED = datetime(2026, 10, 11, 23, 30, tzinfo=UTC)

# Нормативы ADR 0017 п. 2 (seed миграции 0008), минуты.
POLICY = {"app_crash": 240, "navigation": 480, "sim": 480, "audio": 1440, "maintenance": 2880}


@pytest.mark.parametrize(("category", "minutes"), sorted(POLICY.items()))
def test_due_at_is_calendar_time(category, minutes):
    # Календарное время 24/7: через полночь и выходные без пауз.
    assert due_at(CREATED, minutes) - CREATED == timedelta(minutes=minutes)


def test_due_at_rejects_non_positive_policy():
    with pytest.raises(ValueError):
        due_at(CREATED, 0)


@pytest.mark.parametrize(
    ("status", "offset", "expected"),
    [
        (TicketStatus.NEW, timedelta(seconds=1), True),
        (TicketStatus.IN_PROGRESS, timedelta(seconds=1), True),
        (TicketStatus.WAITING_VENDOR, timedelta(hours=5), True),  # пауз у SLA нет
        (TicketStatus.IN_PROGRESS, timedelta(0), False),  # ровно в срок — ещё не просрочен
        (TicketStatus.NEW, -timedelta(seconds=1), False),
        (TicketStatus.RESOLVED, timedelta(days=3), False),  # решённый не просрочен
    ],
)
def test_is_overdue(status, offset, expected):
    sla_due_at = due_at(CREATED, 240)
    assert is_overdue(sla_due_at, status, sla_due_at + offset) is expected
