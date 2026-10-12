"""Показатели дашборда за период — только по витрине фактов (ADR 0020 п. 1).

Формулы — ADR 0020 п. 4–8 и глоссарий («Период аналитики», «Время решения тикета»,
«Проблемная модель», «Конверсия в ТО»). Часы округляются до 0,01, доли — до 0,0001;
`null` — пустая выборка или нулевой знаменатель.
"""

from dataclasses import dataclass
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from sqlalchemy import ColumnElement, Numeric, Select, cast, func, select
from sqlalchemy.orm import Session

from app.core.errors import ApiError
from app.domain.analytics.views import reminder_fact, ticket_fact, vehicle_model_fact
from app.models import AnalyticsRefresh, VehicleModel
from app.models.enums import TicketCategory

PERIOD_MAX_DAYS = 366
HOURS_DIGITS = 2
RATE_STEP = Decimal("0.0001")


@dataclass(frozen=True)
class Period:
    """Даты по Минску, обе включительно (ADR 0020 п. 4)."""

    date_from: date
    date_to: date

    def __post_init__(self) -> None:
        if self.date_from > self.date_to:
            raise _period_error("date_from", "INVALID_PERIOD", "Начало периода позже конца")
        if (self.date_to - self.date_from).days + 1 > PERIOD_MAX_DAYS:
            raise _period_error(
                "date_to", "PERIOD_TOO_LONG", f"Период длиннее {PERIOD_MAX_DAYS} дней"
            )


def _period_error(field: str, code: str, message: str) -> ApiError:
    return ApiError(422, code, message, details={"fields": [{"loc": ["query", field]}]})


def _filters(
    columns: Any, period: Period, vehicle_model_id: int | None = None
) -> list[ColumnElement[bool]]:
    """Факты периода (по дате создания) и, если задана, модели авто."""
    where = [columns.created_on.between(period.date_from, period.date_to)]
    if vehicle_model_id is not None:
        where.append(columns.vehicle_model_id == vehicle_model_id)
    return where


def _hours(value: Any) -> ColumnElement[Decimal]:
    """Округление в БД — по десятичной арифметике (половина — от нуля), без ошибок float."""
    return func.round(cast(value, Numeric), HOURS_DIGITS)


def _float(value: Decimal | None) -> float | None:
    return None if value is None else float(value)


def _rate(part: int, total: int) -> float | None:
    if not total:
        return None
    return float((Decimal(part) / Decimal(total)).quantize(RATE_STEP, ROUND_HALF_UP))


def computed_at(db: Session, *views: Any) -> datetime:
    """Свежесть ответа — самое раннее обновление витрин, по которым он построен (п. 3).

    Читается до данных: если витрину обновят между запросами, ответ занизит свежесть,
    но не завысит её.
    """
    return db.execute(
        select(func.min(AnalyticsRefresh.refreshed_at)).where(
            AnalyticsRefresh.view_name.in_([v.name for v in views])
        )
    ).scalar_one()


# --- A-05: время реакции и решения ------------------------------------------------------------


def ticket_resolution(
    db: Session,
    period: Period,
    vehicle_model_id: int | None = None,
    category: TicketCategory | None = None,
) -> dict[str, Any]:
    fresh = computed_at(db, ticket_fact)
    f = ticket_fact.c
    where = _filters(f, period, vehicle_model_id)
    if category is not None:
        where.append(f.category == category)
    row = db.execute(
        select(
            func.count().label("created"),
            # Время решения есть только у решённых сейчас тикетов (п. 5).
            func.count(f.resolution_hours).label("resolved"),
            func.count().filter(f.resolved_overdue).label("overdue"),
            _hours(func.avg(f.first_response_hours)).label("avg_first_response"),
            _hours(func.avg(f.resolution_hours)).label("avg_resolution"),
            _hours(func.percentile_cont(0.5).within_group(f.resolution_hours)).label("median"),
        ).where(*where)
    ).one()
    return {
        "date_from": period.date_from,
        "date_to": period.date_to,
        "tickets_created": row.created,
        "tickets_resolved": row.resolved,
        "tickets_resolved_overdue": row.overdue,
        "avg_first_response_hours": _float(row.avg_first_response),
        "avg_resolution_hours": _float(row.avg_resolution),
        "median_resolution_hours": _float(row.median),
        "computed_at": fresh,
    }


# --- A-06: проблемные модели ------------------------------------------------------------------


def problem_models_stmt(period: Period) -> Select[Any]:
    """Модели с тикетами за период: (VehicleModel, всего, активных авто, по категориям…)."""
    f = ticket_fact.c
    counts = (
        select(
            f.vehicle_model_id,
            func.count().label("tickets_total"),
            *(
                func.count().filter(f.category == category).label(category.value)
                for category in TicketCategory
            ),
        )
        .where(*_filters(f, period))
        .group_by(f.vehicle_model_id)
        .subquery()
    )
    return (
        select(
            VehicleModel,
            counts.c.tickets_total,
            func.coalesce(vehicle_model_fact.c.vehicles_total, 0),
            *(counts.c[category.value] for category in TicketCategory),
        )
        .join(counts, counts.c.vehicle_model_id == VehicleModel.id)
        .outerjoin(vehicle_model_fact, vehicle_model_fact.c.vehicle_model_id == VehicleModel.id)
        .order_by(
            counts.c.tickets_total.desc(),
            VehicleModel.brand,
            VehicleModel.model,
            VehicleModel.trim,
            VehicleModel.id,
        )
    )


def problem_model_item(row: Any) -> dict[str, Any]:
    model, tickets_total, vehicles_total, *by_category = row
    return {
        "vehicle_model": model,
        "tickets_total": tickets_total,
        "vehicles_total": vehicles_total,
        "by_category": [
            {"category": category, "count": count}
            for category, count in zip(TicketCategory, by_category, strict=True)
        ],
    }


def problem_models_computed_at(db: Session) -> datetime:
    return computed_at(db, ticket_fact, vehicle_model_fact)


# --- A-06: конверсия в ТО ---------------------------------------------------------------------


def maintenance_conversion(
    db: Session, period: Period, vehicle_model_id: int | None = None
) -> dict[str, Any]:
    fresh = computed_at(db, ticket_fact, reminder_fact)
    t, r = ticket_fact.c, reminder_fact.c
    tickets = db.execute(
        select(
            func.count().label("total"),
            func.count().filter(t.has_maintenance).label("with_maintenance"),
        ).where(*_filters(t, period, vehicle_model_id))
    ).one()
    reminders = db.execute(
        select(
            func.count().label("recipients"),
            func.count().filter(r.opened).label("opened"),
            func.count().filter(r.has_maintenance).label("with_maintenance"),
        ).where(*_filters(r, period, vehicle_model_id))
    ).one()
    return {
        "date_from": period.date_from,
        "date_to": period.date_to,
        "tickets_total": tickets.total,
        "tickets_with_maintenance": tickets.with_maintenance,
        "ticket_to_maintenance_rate": _rate(tickets.with_maintenance, tickets.total),
        "notifications_recipients": reminders.recipients,
        "notifications_opened": reminders.opened,
        "recipients_with_maintenance": reminders.with_maintenance,
        "notification_to_maintenance_rate": _rate(reminders.with_maintenance, reminders.recipients),
        "computed_at": fresh,
    }
