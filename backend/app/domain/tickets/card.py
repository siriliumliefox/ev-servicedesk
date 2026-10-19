"""Карточка тикета — результат сценариев getTicket и записей тикета (ADR 0017)."""

from dataclasses import dataclass

from app.domain.aggregates.service import AggregateStatusView
from app.models import AppUser, Ticket


@dataclass(frozen=True)
class TicketCard:
    """Карточка тикета: тикет со связями, статусы агрегатов авто на момент обращения и клиент —
    владелец авто (#104: инженер видит, кому отвечает и не заблокирован ли он)."""

    ticket: Ticket
    aggregate_statuses: list[AggregateStatusView]
    client: AppUser
