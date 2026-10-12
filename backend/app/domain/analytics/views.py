"""Витрина аналитики — materialized view миграции 0013 (ADR 0020 п. 1).

ORM-моделей у витрины нет: схема меняется только миграцией, здесь — описание колонок для
запросов. Колонки должны совпадать с миграцией (проверяет tests/db/test_analytics_views.py).
"""

from sqlalchemy import BigInteger, Boolean, Column, Date, Numeric, table

from app.models.enums import TicketCategory, pg_enum

ticket_fact = table(
    "analytics_ticket_fact",
    Column("ticket_id", BigInteger),
    Column("created_on", Date),
    Column("vehicle_model_id", BigInteger),
    Column("category", pg_enum(TicketCategory, "ticket_category")),
    Column("first_response_hours", Numeric),
    Column("resolution_hours", Numeric),
    Column("resolved_overdue", Boolean),
    Column("has_maintenance", Boolean),
)

reminder_fact = table(
    "analytics_reminder_fact",
    Column("recipient_id", BigInteger),
    Column("created_on", Date),
    Column("vehicle_model_id", BigInteger),
    Column("opened", Boolean),
    Column("has_maintenance", Boolean),
)

vehicle_model_fact = table(
    "analytics_vehicle_model_fact",
    Column("vehicle_model_id", BigInteger),
    Column("vehicles_total", BigInteger),
)

# Порядок обновления; у каждой витрины — строка в analytics_refresh.
VIEWS = (ticket_fact, reminder_fact, vehicle_model_fact)
