"""Время бизнеса: сервис работает в Гомеле (Europe/Minsk)."""

from datetime import date, datetime
from zoneinfo import ZoneInfo

# Дата работ — по времени сервиса, иначе после полуночи по Минску «сегодня» по UTC
# ещё вчера, а запись сегодняшней работы отклонялась бы как будущая.
BUSINESS_TZ = ZoneInfo("Europe/Minsk")


def today_in_business_tz() -> date:
    """«Сегодня» по Минску: дата работ, замен, релизов и напоминаний."""
    return datetime.now(BUSINESS_TZ).date()
