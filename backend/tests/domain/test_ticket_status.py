"""Граф статусов тикета и правило назначения (ADR 0017 п. 4–5): чистые функции."""

from datetime import UTC, datetime, timedelta
from itertools import product

import pytest

from app.domain.tickets.status import (
    TRANSITIONS,
    InvalidTransition,
    StatusChange,
    after_assignment,
    transition,
)
from app.models.enums import TicketStatus

NEW, IN_PROGRESS, WAITING, RESOLVED = (
    TicketStatus.NEW,
    TicketStatus.IN_PROGRESS,
    TicketStatus.WAITING_VENDOR,
    TicketStatus.RESOLVED,
)
NOW = datetime(2026, 10, 11, 12, 0, tzinfo=UTC)
EARLIER = NOW - timedelta(days=1)


def test_graph_is_exactly_adr_0017():
    assert TRANSITIONS == {
        (IN_PROGRESS, WAITING),
        (WAITING, IN_PROGRESS),
        (IN_PROGRESS, RESOLVED),
        (WAITING, RESOLVED),
        (RESOLVED, IN_PROGRESS),
    }


@pytest.mark.parametrize("current", list(TicketStatus))
def test_same_status_is_noop(current):
    resolved_at = EARLIER if current is RESOLVED else None
    assert transition(current, current, resolved_at, NOW) is None


@pytest.mark.parametrize(
    ("current", "target"),
    [(c, t) for c, t in product(TicketStatus, repeat=2) if c != t and (c, t) not in TRANSITIONS],
)
def test_outside_graph_is_rejected(current, target):
    with pytest.raises(InvalidTransition) as info:
        transition(current, target, None, NOW)
    assert (info.value.current, info.value.target) == (current, target)


def test_new_to_in_progress_only_via_claim_or_assign():
    with pytest.raises(InvalidTransition):
        transition(NEW, IN_PROGRESS, None, NOW)


@pytest.mark.parametrize("current", [IN_PROGRESS, WAITING])
def test_resolve_sets_resolved_at(current):
    assert transition(current, RESOLVED, None, NOW) == StatusChange(RESOLVED, NOW)


def test_reopen_clears_resolved_at():
    assert transition(RESOLVED, IN_PROGRESS, EARLIER, NOW) == StatusChange(IN_PROGRESS, None)


def test_waiting_vendor_round_trip_keeps_resolved_at_empty():
    assert transition(IN_PROGRESS, WAITING, None, NOW) == StatusChange(WAITING, None)
    assert transition(WAITING, IN_PROGRESS, None, NOW) == StatusChange(IN_PROGRESS, None)


@pytest.mark.parametrize(
    ("current", "assignee", "expected"),
    [
        (NEW, 7, IN_PROGRESS),  # назначение из очереди
        (IN_PROGRESS, 8, IN_PROGRESS),  # переназначение статус не меняет
        (WAITING, 8, WAITING),
        (IN_PROGRESS, None, NEW),  # снятие — обратно в очередь
        (WAITING, None, NEW),
        (NEW, None, NEW),
    ],
)
def test_after_assignment(current, assignee, expected):
    assert after_assignment(current, assignee) is expected


def test_resolved_ticket_is_not_assigned():
    with pytest.raises(ValueError):
        after_assignment(RESOLVED, 7)
