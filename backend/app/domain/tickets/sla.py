"""SLA — срок решения тикета (ADR 0017 п. 1–3). Чистые функции, `now` — параметр.

Срок вычисляется один раз при создании (created_at + норматив категории из
`ticket_sla_policy`) и не меняется. Просрочка — `Ticket.is_overdue` (выражение SQL, чтобы
поле ответа и фильтр `overdue` совпадали); здесь — то же правило для проверок без БД.
"""

from datetime import datetime, timedelta

from app.models.enums import TicketStatus


def due_at(created_at: datetime, resolution_minutes: int) -> datetime:
    """Срок решения: календарное время 24/7, без пауз (ожидание вендора не останавливает)."""
    if resolution_minutes <= 0:
        raise ValueError("норматив SLA должен быть больше 0 минут")
    return created_at + timedelta(minutes=resolution_minutes)


def is_overdue(sla_due_at: datetime, status: TicketStatus, now: datetime) -> bool:
    """now > sla_due_at и тикет не решён; решённый тикет не просрочен, даже если решён поздно."""
    return status is not TicketStatus.RESOLVED and now > sla_due_at
