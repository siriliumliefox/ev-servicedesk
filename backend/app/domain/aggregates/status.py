"""Статус агрегата «светофор» (Глава 5, ADR 0009).

Правила — docs/specs/AGGREGATE_STATUS_ALGORITHM.md;
сценарии — docs/specs/aggregate_status_scenarios.yaml.
Чистые функции: без БД, HTTP и системных часов (`today` передаётся параметром).
"""

import calendar
import math
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from enum import StrEnum
from fractions import Fraction


class TrafficLight(StrEnum):
    GREEN = "green"
    YELLOW = "yellow"
    RED = "red"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class Regulation:
    """Активная версия регламента для (модель авто, агрегат); хотя бы один интервал > 0."""

    interval_km: int | None = None
    interval_months: int | None = None


@dataclass(frozen=True)
class Replacement:
    """Последняя замена (`vehicle_aggregate_status`); любое поле может быть неизвестно."""

    replaced_at: date | None = None
    mileage: int | None = None


@dataclass(frozen=True)
class Thresholds:
    """Пороги `aggregate_status_thresholds`: green < yellow_from ≤ yellow ≤ red_above < red."""

    yellow_from_percent: int = 70
    red_above_percent: int = 100


@dataclass(frozen=True)
class AggregateStatusResult:
    status: TrafficLight
    percentage: Decimal | None = None
    remaining_km: int | None = None
    remaining_days: int | None = None


def add_months(start: date, months: int) -> date:
    """Календарные месяцы с ограничением дня концом месяца: 31.01 + 1 = 28.02 (29.02)."""
    year, month0 = divmod(start.month - 1 + months, 12)
    year += start.year
    month = month0 + 1
    return date(year, month, min(start.day, calendar.monthrange(year, month)[1]))


def _truncate(p: Fraction) -> Decimal:
    """Процент для показа: вниз до 0,1. Цвет определяется точным p, не этим значением."""
    return Decimal(math.floor(p * 10)) / 10


def compute_status(
    regulation: Regulation | None,
    last: Replacement | None,
    current_mileage: int,
    today: date,
    thresholds: Thresholds,
) -> AggregateStatusResult | None:
    """None — агрегат не отслеживается (нет активного регламента) и в ответ не входит."""
    if regulation is None:
        return None
    last = last or Replacement()
    components: list[Fraction] = []
    remaining_km = remaining_days = None

    if regulation.interval_km is not None and last.mileage is not None:
        used_km = max(0, current_mileage - last.mileage)
        components.append(Fraction(100 * used_km, regulation.interval_km))
        remaining_km = regulation.interval_km - used_km

    if regulation.interval_months is not None and last.replaced_at is not None:
        due = add_months(last.replaced_at, regulation.interval_months)
        elapsed_days = max(0, (today - last.replaced_at).days)
        components.append(Fraction(100 * elapsed_days, (due - last.replaced_at).days))
        remaining_days = (due - today).days

    if not components:
        return AggregateStatusResult(TrafficLight.UNKNOWN)

    p = max(components)
    if p < thresholds.yellow_from_percent:
        status = TrafficLight.GREEN
    elif p <= thresholds.red_above_percent:
        status = TrafficLight.YELLOW
    else:
        status = TrafficLight.RED
    return AggregateStatusResult(status, _truncate(p), remaining_km, remaining_days)


def becomes_current(current: Replacement | None, replaced_at: date) -> bool:
    """Обновит ли новая замена `vehicle_aggregate_status` (иначе — только история, E5–E7).

    Текущей становится замена с наибольшей датой; при равной дате — последняя зафиксированная.
    """
    if current is None or current.replaced_at is None:
        return True
    return replaced_at >= current.replaced_at
