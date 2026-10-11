"""Граф статусов тикета и правило назначения (ADR 0017 п. 4–5).

Чистые функции: без БД, HTTP и системных часов (`now` передаётся параметром).
"""

from dataclasses import dataclass
from datetime import datetime

from app.models.enums import TicketStatus

NEW = TicketStatus.NEW
IN_PROGRESS = TicketStatus.IN_PROGRESS
WAITING_VENDOR = TicketStatus.WAITING_VENDOR
RESOLVED = TicketStatus.RESOLVED

# Переходы updateTicketStatus. new → in_progress — только claim или назначение админом;
# в new тикет возвращает только снятие исполнителя (`after_assignment`).
TRANSITIONS: frozenset[tuple[TicketStatus, TicketStatus]] = frozenset(
    {
        (IN_PROGRESS, WAITING_VENDOR),
        (WAITING_VENDOR, IN_PROGRESS),
        (IN_PROGRESS, RESOLVED),
        (WAITING_VENDOR, RESOLVED),
        (RESOLVED, IN_PROGRESS),  # переоткрытие; срок SLA не продлевается
    }
)


class InvalidTransition(Exception):
    """Переход вне графа (→ 409 INVALID_STATUS_TRANSITION)."""

    def __init__(self, current: TicketStatus, target: TicketStatus) -> None:
        super().__init__(f"{current} → {target}")
        self.current = current
        self.target = target


@dataclass(frozen=True)
class StatusChange:
    status: TicketStatus
    resolved_at: datetime | None


def transition(
    current: TicketStatus,
    target: TicketStatus,
    resolved_at: datetime | None,
    now: datetime,
) -> StatusChange | None:
    """Новое состояние после смены статуса; None — запрошен текущий статус (без изменений).

    resolved_at заполнен тогда и только тогда, когда статус resolved (A-05): решение ставит
    `now`, переоткрытие очищает.
    """
    if target == current:
        return None
    if (current, target) not in TRANSITIONS:
        raise InvalidTransition(current, target)
    if target is RESOLVED:
        return StatusChange(target, now)
    return StatusChange(target, None if current is RESOLVED else resolved_at)


def after_assignment(current: TicketStatus, assignee_id: int | None) -> TicketStatus:
    """Статус после assignTicket для нерешённого тикета (решённый — 409 у вызывающего).

    Назначение на new переводит в in_progress, переназначение статус не меняет,
    снятие исполнителя возвращает тикет в очередь (new).
    """
    if current is RESOLVED:
        raise ValueError("решённый тикет не назначается — 409 TICKET_RESOLVED")
    if assignee_id is None:
        return NEW
    return IN_PROGRESS if current is NEW else current
