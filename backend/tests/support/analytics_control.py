"""Контрольный набор аналитики (Глава 16, ADR 0020 п. 9) и сверка ответов API с ручным расчётом.

Данные и ожидаемые значения — `docs/ANALYTICS_CONTROL.md` (ручной расчёт). Набор используют:
- тест backend-ci `tests/api/test_analytics_control.py` — `load()` + `compare()`;
- smoke образа `scripts/smoke_backend_image.sh` — тот же модуль из примонтированного каталога
  `tests` (в образ не входит):
  `python -m tests.support.analytics_control load` — данные и администратор контроля;
  `python -m tests.support.analytics_control verify --base URL` — запросы к API и сверка.
Пароль администратора — переменная CONTROL_ADMIN_PASSWORD; модуль его не печатает.

Время — по Минску (UTC+3): границы периода проверяются тикетами и напоминаниями около полуночи.
Набор изолирован: свои модели «Контроль …», клиенты и авто; период — март 2026 и соседние дни.
"""

import argparse
import os
import sys
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.time import BUSINESS_TZ
from app.models import (
    AggregateType,
    AppUser,
    MaintenanceRecord,
    Notification,
    NotificationDelivery,
    NotificationRecipient,
    PushToken,
    Ticket,
    Vehicle,
    VehicleModel,
)
from app.models.enums import NotificationType, TicketCategory, TicketStatus, UserRole

ADMIN_PHONE = "+375000016001"
BRAND = "Контроль"
SLA_HOURS = {  # нормативы миграции 0008 (ADR 0017 п. 2)
    TicketCategory.APP_CRASH: 4,
    TicketCategory.NAVIGATION: 8,
    TicketCategory.SIM: 8,
    TicketCategory.AUDIO: 24,
    TicketCategory.MAINTENANCE: 48,
}


def minsk(day: str, clock: str) -> datetime:
    return datetime.fromisoformat(f"{day}T{clock}").replace(tzinfo=BUSINESS_TZ)


@dataclass(frozen=True)
class TicketSpec:
    vehicle: str
    category: TicketCategory
    created: datetime
    first_response_h: float | None
    resolved_h: float | None
    reopened: bool = False


@dataclass(frozen=True)
class ReminderSpec:
    vehicle: str
    created: datetime
    # Доставки на устройства получателя: имя токена → открыта ли.
    deliveries: dict[str, bool]


# Модели: «Альфа» — V1, V2, V3 (V3 удалено после тикета), «Бета» — V4, «Гамма» — V5, V6.
VEHICLES = {
    "V1": ("Альфа", "C1", False),
    "V2": ("Альфа", "C2", False),
    "V3": ("Альфа", "C3", True),
    "V4": ("Бета", "C4", False),
    "V5": ("Гамма", "C5", False),
    "V6": ("Гамма", "C6", False),
}
TOKENS = {"t1a": "C1", "t1b": "C1", "t2": "C2", "t5": "C5"}

N, A, S, X, M = (
    TicketCategory.NAVIGATION,
    TicketCategory.AUDIO,
    TicketCategory.SIM,
    TicketCategory.APP_CRASH,
    TicketCategory.MAINTENANCE,
)
TICKETS = {
    # 1 марта 00:30 по Минску = 28 февраля по UTC; решён позже срока SLA (8 ч).
    "T1": TicketSpec("V1", N, minsk("2026-03-01", "00:30"), 1.0, 10.0),
    "T2": TicketSpec("V1", A, minsk("2026-03-05", "10:00"), 0.5, 6.0),
    # Переоткрыт и ещё не решён — не решённый.
    "T3": TicketSpec("V2", X, minsk("2026-03-10", "09:00"), 0.25, None, reopened=True),
    # Авто V3 удалено позже — тикет учитывается; работа ТО по тикету.
    "T4": TicketSpec("V3", M, minsk("2026-03-12", "12:00"), 2.0, 30.0),
    "T5": TicketSpec("V4", S, minsk("2026-03-20", "15:00"), None, None),
    # 31 марта 23:59 по Минску — последняя минута периода; решён с просрочкой; работа ТО.
    "T6": TicketSpec("V4", N, minsk("2026-03-31", "23:59"), 1.0, 9.0),
    # 1 апреля 00:10 по Минску = 31 марта по UTC — вне марта.
    "T7": TicketSpec("V5", A, minsk("2026-04-01", "00:10"), 0.1, 1.0),
    # 28 февраля — вне марта, но в периоде «февраль–март»; работа ТО по тикету.
    "T8": TicketSpec("V5", M, minsk("2026-02-28", "23:50"), None, 5.0),
    # Решён ровно в срок SLA (4 ч) — не просрочен (строгое «позже срока»).
    "T9": TicketSpec("V6", X, minsk("2026-03-15", "08:00"), 0.2, 4.0),
    # Первичный ответ через 1 ч 31 мин 30 с: среднее 0,925 ч округляется до 0,93.
    "T10": TicketSpec("V6", S, minsk("2026-03-25", "11:00"), 1.525, 7.0),
}

# Работы ТО: (авто, тикет или None — записал администратор, дата работ).
MAINTENANCE = [
    ("V3", "T4", "2026-03-13"),
    ("V4", "T6", "2026-04-01"),
    ("V5", "T8", "2026-03-01"),  # раньше напоминания R3 — в его окно не входит
    ("V1", None, "2026-03-20"),  # окно R1
    ("V2", None, "2026-04-02"),  # 3 марта + 30 дней — граница окна R2 (входит); окно R6
    ("V5", None, "2026-04-04"),  # 4 марта + 31 день — вне окна R3
]

REMINDERS = {
    "R1": ReminderSpec("V1", minsk("2026-03-02", "10:00"), {"t1a": True, "t1b": False}),
    "R2": ReminderSpec("V2", minsk("2026-03-03", "10:00"), {"t2": False}),
    "R3": ReminderSpec("V5", minsk("2026-03-04", "10:00"), {"t5": True}),
    # Без устройств — получение без push; окно 30 дней ещё «не закрыто» на конец марта.
    "R4": ReminderSpec("V6", minsk("2026-03-31", "23:30"), {}),
    # 1 апреля 01:00 по Минску = 31 марта по UTC — вне марта.
    "R5": ReminderSpec("V1", minsk("2026-04-01", "01:00"), {"t1a": True}),
    # Второе напоминание тому же клиенту — отдельное получение.
    "R6": ReminderSpec("V2", minsk("2026-03-28", "10:00"), {"t2": True}),
}


@dataclass
class World:
    models: dict[str, VehicleModel]
    vehicles: dict[str, Vehicle]
    tickets: dict[str, Ticket]


def _hours(start: datetime, hours: float | None) -> datetime | None:
    return None if hours is None else start + timedelta(hours=hours)


def load(db: Session, admin_password_hash: str | None = None) -> World:
    """Создаёт контрольный набор (и администратора контроля, если задан хэш пароля)."""
    if admin_password_hash is not None:
        db.add(AppUser(phone=ADMIN_PHONE, role=UserRole.ADMIN, password_hash=admin_password_hash))
    models = {
        name: VehicleModel(brand=BRAND, model=name)
        for name in sorted({v[0] for v in VEHICLES.values()})
    }
    db.add_all(models.values())
    clients = {
        name: AppUser(phone=f"+37500001610{i}", role=UserRole.CLIENT)
        for i, name in enumerate(sorted({v[1] for v in VEHICLES.values()}), start=1)
    }
    db.add_all(clients.values())
    db.flush()
    vehicles = {
        name: Vehicle(
            user_id=clients[client].id,
            vehicle_model_id=models[model].id,
            vin=f"CTRLA{i:012d}",
            mileage=10_000,
        )
        for i, (name, (model, client, _)) in enumerate(VEHICLES.items(), start=1)
    }
    db.add_all(vehicles.values())
    db.flush()

    tickets = {}
    for name, spec in TICKETS.items():
        resolved_at = _hours(spec.created, spec.resolved_h)
        tickets[name] = Ticket(
            vehicle_id=vehicles[spec.vehicle].id,
            category=spec.category,
            status=(
                TicketStatus.RESOLVED
                if resolved_at
                else TicketStatus.IN_PROGRESS
                if spec.reopened or spec.first_response_h is not None
                else TicketStatus.NEW
            ),
            description=f"Контрольный тикет {name}",
            created_at=spec.created,
            sla_due_at=spec.created + timedelta(hours=SLA_HOURS[spec.category]),
            first_response_at=_hours(spec.created, spec.first_response_h),
            resolved_at=resolved_at,
        )
    db.add_all(tickets.values())
    db.flush()

    db.add_all(
        MaintenanceRecord(
            vehicle_id=vehicles[vehicle].id,
            ticket_id=tickets[ticket].id if ticket else None,
            performed_at=date.fromisoformat(day),
            mileage_at_service=10_000,
            description="Контрольная работа ТО",
        )
        for vehicle, ticket, day in MAINTENANCE
    )

    tokens = {
        name: PushToken(user_id=clients[client].id, token=f"control-token-{name}")
        for name, client in TOKENS.items()
    }
    db.add_all(tokens.values())
    db.flush()
    oil = _engine_oil_id(db)
    for name, spec in REMINDERS.items():
        vehicle = vehicles[spec.vehicle]
        notification = Notification(
            type=NotificationType.MAINTENANCE,
            vehicle_id=vehicle.id,
            aggregate_type_id=oil,
            message=f"Контрольное напоминание {name}",
            created_at=spec.created,
        )
        db.add(notification)
        db.flush()
        db.add(NotificationRecipient(notification_id=notification.id, user_id=vehicle.user_id))
        for token, opened in spec.deliveries.items():
            sent = spec.created + timedelta(seconds=5)
            db.add(
                NotificationDelivery(
                    notification_id=notification.id,
                    push_token_id=tokens[token].id,
                    delivered_at=sent,
                    opened_at=sent + timedelta(minutes=10) if opened else None,
                )
            )
    # Новость с открытым push — не напоминание о ТО, в конверсию не входит.
    news = Notification(
        type=NotificationType.NEWS,
        message="Контрольная новость",
        created_at=minsk("2026-03-02", "12:00"),
    )
    db.add(news)
    db.flush()
    db.add(NotificationRecipient(notification_id=news.id, user_id=clients["C1"].id))
    db.add(
        NotificationDelivery(
            notification_id=news.id,
            push_token_id=tokens["t1a"].id,
            delivered_at=news.created_at,
            opened_at=news.created_at + timedelta(minutes=1),
        )
    )
    # V3 удалено после тикета T4.
    vehicles["V3"].deleted_at = minsk("2026-03-14", "09:00")
    db.commit()
    return World(models, vehicles, tickets)


def _engine_oil_id(db: Session) -> int:
    return db.execute(
        select(AggregateType.id).where(AggregateType.code == "engine_oil")
    ).scalar_one()


# --- ожидаемые ответы (ручной расчёт — docs/ANALYTICS_CONTROL.md) --------------------------------

MARCH = {"date_from": "2026-03-01", "date_to": "2026-03-31"}
FEB_MARCH = {"date_from": "2026-02-01", "date_to": "2026-03-31"}
APRIL_1 = {"date_from": "2026-04-01", "date_to": "2026-04-01"}


def _categories(**counts: int) -> list[dict[str, Any]]:
    return [{"category": c.value, "count": counts.get(c.value, 0)} for c in TicketCategory]


def _model(name: str, tickets: int, vehicles: int, **counts: int) -> dict[str, Any]:
    return {
        "vehicle_model": {"brand": BRAND, "model": name, "trim": None},
        "tickets_total": tickets,
        "vehicles_total": vehicles,
        "by_category": _categories(**counts),
    }


def _resolution(period: dict, created, resolved, overdue, first, avg, median) -> dict[str, Any]:
    return period | {
        "tickets_created": created,
        "tickets_resolved": resolved,
        "tickets_resolved_overdue": overdue,
        "avg_first_response_hours": first,
        "avg_resolution_hours": avg,
        "median_resolution_hours": median,
    }


def _conversion(period: dict, tickets, with_mt, rate, recipients, opened, rec_mt, rec_rate):
    return period | {
        "tickets_total": tickets,
        "tickets_with_maintenance": with_mt,
        "ticket_to_maintenance_rate": rate,
        "notifications_recipients": recipients,
        "notifications_opened": opened,
        "recipients_with_maintenance": rec_mt,
        "notification_to_maintenance_rate": rec_rate,
    }


@dataclass(frozen=True)
class Query:
    """Запрос контроля: путь, параметры (модель — по имени) и ожидаемое тело без computed_at."""

    name: str
    path: str
    params: dict[str, Any]
    expected: dict[str, Any]
    model: str | None = None


QUERIES = [
    Query(
        "A1", "/v1/analytics/ticket-resolution", MARCH, _resolution(MARCH, 8, 6, 2, 0.93, 11.0, 8.0)
    ),
    Query(
        "A2",
        "/v1/analytics/ticket-resolution",
        MARCH | {"category": "navigation"},
        _resolution(MARCH, 1, 1, 1, 1.0, 10.0, 10.0),
        model="Альфа",
    ),
    Query(
        "A3",
        "/v1/analytics/ticket-resolution",
        MARCH,
        _resolution(MARCH, 2, 1, 1, 1.0, 9.0, 9.0),
        model="Бета",
    ),
    Query(
        "A4",
        "/v1/analytics/ticket-resolution",
        MARCH | {"category": "maintenance"},
        _resolution(MARCH, 0, 0, 0, None, None, None),
        model="Гамма",
    ),
    Query(
        "A5",
        "/v1/analytics/ticket-resolution",
        FEB_MARCH,
        _resolution(FEB_MARCH, 9, 7, 2, 0.93, 10.14, 7.0),
    ),
    Query(
        "A6",
        "/v1/analytics/ticket-resolution",
        APRIL_1,
        _resolution(APRIL_1, 1, 1, 0, 0.1, 1.0, 1.0),
    ),
    Query(
        "P1",
        "/v1/analytics/problem-models",
        MARCH | {"page": 1, "page_size": 2},
        {
            "items": [
                _model("Альфа", 4, 2, navigation=1, audio=1, app_crash=1, maintenance=1),
                _model("Бета", 2, 1, navigation=1, sim=1),
            ],
            "meta": {"page": 1, "page_size": 2, "total_items": 3, "total_pages": 2},
        },
    ),
    Query(
        "P2",
        "/v1/analytics/problem-models",
        MARCH | {"page": 2, "page_size": 2},
        {
            "items": [_model("Гамма", 2, 2, sim=1, app_crash=1)],
            "meta": {"page": 2, "page_size": 2, "total_items": 3, "total_pages": 2},
        },
    ),
    Query(
        "P3",
        "/v1/analytics/problem-models",
        FEB_MARCH,
        {
            "items": [
                _model("Альфа", 4, 2, navigation=1, audio=1, app_crash=1, maintenance=1),
                _model("Гамма", 3, 2, sim=1, app_crash=1, maintenance=1),
                _model("Бета", 2, 1, navigation=1, sim=1),
            ],
            "meta": {"page": 1, "page_size": 20, "total_items": 3, "total_pages": 1},
        },
    ),
    Query(
        "C1",
        "/v1/analytics/maintenance-conversion",
        MARCH,
        _conversion(MARCH, 8, 2, 0.25, 5, 3, 3, 0.6),
    ),
    Query(
        "C2",
        "/v1/analytics/maintenance-conversion",
        MARCH,
        _conversion(MARCH, 4, 1, 0.25, 3, 2, 3, 1.0),
        model="Альфа",
    ),
    Query(
        "C3",
        "/v1/analytics/maintenance-conversion",
        MARCH,
        _conversion(MARCH, 2, 1, 0.5, 0, 0, 0, None),
        model="Бета",
    ),
    Query(
        "C4",
        "/v1/analytics/maintenance-conversion",
        MARCH,
        _conversion(MARCH, 2, 0, 0.0, 2, 1, 0, 0.0),
        model="Гамма",
    ),
    Query(
        "C5",
        "/v1/analytics/maintenance-conversion",
        FEB_MARCH,
        _conversion(FEB_MARCH, 9, 3, 0.3333, 5, 3, 3, 0.6),
    ),
]


def params(query: Query, model_ids: dict[str, int]) -> dict[str, Any]:
    if query.model is None:
        return dict(query.params)
    return query.params | {"vehicle_model_id": model_ids[query.model]}


def compare(query: Query, body: dict[str, Any]) -> list[str]:
    """Расхождения ответа с ручным расчётом (пусто — совпало). computed_at и id не сверяются."""
    actual = dict(body)
    if "computed_at" not in actual:
        return ["нет computed_at"]
    del actual["computed_at"]
    for item in actual.get("items", []):
        item["vehicle_model"] = {k: v for k, v in item["vehicle_model"].items() if k != "id"}
    if actual == query.expected:
        return []
    keys = sorted(set(actual) | set(query.expected))
    return [
        f"{k}: ожидалось {query.expected.get(k)!r}, получено {actual.get(k)!r}"
        for k in keys
        if actual.get(k) != query.expected.get(k)
    ]


def verify(get: Callable[[str, dict[str, Any]], dict[str, Any]], model_ids: dict[str, int]) -> int:
    """Сверка всех запросов: печать PASS/FAIL, число расхождений."""
    failed = 0
    for query in QUERIES:
        problems = compare(query, get(query.path, params(query, model_ids)))
        print(f"{'PASS' if not problems else 'FAIL'}  контроль аналитики {query.name}")
        for problem in problems:
            print(f"      {problem}")
        failed += bool(problems)
    return failed


# --- CLI для smoke образа ---------------------------------------------------------------------


def _cli_load() -> int:
    from app.core.db import get_session_scope
    from app.core.security import hash_password

    with get_session_scope()() as db:
        load(db, hash_password(os.environ["CONTROL_ADMIN_PASSWORD"]))
    print("Контрольный набор аналитики загружен")
    return 0


def _cli_verify(base: str) -> int:
    import httpx

    with httpx.Client(base_url=base, timeout=30) as http:
        r = http.post(
            "/v1/auth/staff/login",
            json={"phone": ADMIN_PHONE, "password": os.environ["CONTROL_ADMIN_PASSWORD"]},
        )
        r.raise_for_status()
        http.headers["Authorization"] = f"Bearer {r.json()['access_token']}"
        models = http.get("/v1/vehicle-models", params={"search": BRAND, "page_size": 100}).json()[
            "items"
        ]
        model_ids = {m["model"]: m["id"] for m in models if m["brand"] == BRAND}

        def get(path: str, query: dict[str, Any]) -> dict[str, Any]:
            response = http.get(path, params=query)
            response.raise_for_status()
            return response.json()

        return 1 if verify(get, model_ids) else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Контрольный набор аналитики (ADR 0020)")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("load")
    check = sub.add_parser("verify")
    check.add_argument("--base", default="http://localhost:8000")
    args = parser.parse_args(argv)
    return _cli_load() if args.command == "load" else _cli_verify(args.base)


if __name__ == "__main__":
    sys.exit(main())
