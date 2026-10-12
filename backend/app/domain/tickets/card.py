"""Карточка тикета — результат сценариев getTicket и записей тикета (ADR 0017)."""

from dataclasses import dataclass

from app.domain.aggregates.service import AggregateStatusView
from app.models import Ticket


@dataclass(frozen=True)
class TicketCard:
    """Карточка тикета: тикет со связями и статусы агрегатов авто на момент обращения."""

    ticket: Ticket
    aggregate_statuses: list[AggregateStatusView]
