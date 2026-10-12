"""SLA — срок решения тикета (ADR 0017 п. 1–3). Чистые функции, `now` — параметр.

Срок вычисляется один раз при создании (created_at + норматив категории из
`ticket_sla_policy`) и не меняется. Просрочка — только `Ticket.is_overdue` (выражение SQL:
поле ответа и фильтр `overdue` совпадают; Python-копия правила удалена ревью главы 17 —
границы проверяет tests/api/test_ticket_checklist.py через БД).
"""

from datetime import datetime, timedelta


def due_at(created_at: datetime, resolution_minutes: int) -> datetime:
    """Срок решения: календарное время 24/7, без пауз (ожидание вендора не останавливает)."""
    if resolution_minutes <= 0:
        raise ValueError("норматив SLA должен быть больше 0 минут")
    return created_at + timedelta(minutes=resolution_minutes)
