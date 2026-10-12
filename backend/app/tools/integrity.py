"""Аудит целостности данных между модулями (Глава 17, ADR 0021 п. 8).

`python -m app.tools.integrity` — именованные SQL-проверки инвариантов, которые не выражены
ограничениями БД, потому что связывают таблицы разных модулей (Auth, Vehicle, Aggregates,
Tickets, Notifications). Печатает только имена проверок, число нарушений и id строк — без ПД.
Код выхода 1 — есть нарушения. Запускается в тестах, на стеке после сквозного сценария и в
мониторинге (главы 26, 28). Только чтение.
"""

import sys
from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.db import get_session_scope

SAMPLE = 10  # id нарушений в отчёте — не больше


@dataclass(frozen=True)
class Check:
    name: str
    description: str
    sql: str  # SELECT id нарушающих строк


# Доступный пользователь — как AppUser.is_available; клиент вправе получать уведомления —
# как notifications.service.eligible_client.
_UNAVAILABLE = "(u.is_active IS FALSE OR u.anonymized_at IS NOT NULL)"
_NO_ACTIVE_CONSENT = (
    "NOT EXISTS (SELECT 1 FROM pd_consent c WHERE c.user_id = u.id AND c.withdrawn_at IS NULL)"
)

CHECKS: tuple[Check, ...] = (
    Check(
        "replacement_without_history",
        "Последняя замена агрегата без записи в истории ТО (замена пишет оба, ADR 0016)",
        """
        SELECT s.id FROM vehicle_aggregate_status s
        WHERE s.last_replaced_at IS NOT NULL AND NOT EXISTS (
            SELECT 1 FROM maintenance_record m
            WHERE m.vehicle_id = s.vehicle_id AND m.aggregate_type_id = s.aggregate_type_id
              AND m.performed_at = s.last_replaced_at
              AND m.mileage_at_service IS NOT DISTINCT FROM s.last_replaced_mileage)
        """,
    ),
    Check(
        "maintenance_record_of_other_vehicle_ticket",
        "Работа ТО привязана к тикету другого авто",
        """
        SELECT m.id FROM maintenance_record m JOIN ticket t ON t.id = m.ticket_id
        WHERE t.vehicle_id <> m.vehicle_id
        """,
    ),
    Check(
        "maintenance_record_by_client",
        "Работу ТО записал клиент (только инженер или администратор)",
        """
        SELECT m.id FROM maintenance_record m JOIN app_user u ON u.id = m.performed_by_user_id
        WHERE u.role = 'client'
        """,
    ),
    Check(
        "vehicle_owner_not_client",
        "Владелец авто — не клиент",
        "SELECT v.id FROM vehicle v JOIN app_user u ON u.id = v.user_id WHERE u.role <> 'client'",
    ),
    Check(
        "ticket_assignee_is_client",
        "Исполнитель тикета — клиент",
        """
        SELECT t.id FROM ticket t JOIN app_user u ON u.id = t.assigned_engineer_id
        WHERE u.role = 'client'
        """,
    ),
    Check(
        "ticket_created_for_deleted_vehicle",
        "Тикет создан после удаления авто",
        """
        SELECT t.id FROM ticket t JOIN vehicle v ON v.id = t.vehicle_id
        WHERE v.deleted_at IS NOT NULL AND t.created_at > v.deleted_at
        """,
    ),
    Check(
        "client_message_in_foreign_ticket",
        "Клиент написал в тикет чужого авто",
        """
        SELECT msg.id FROM ticket_message msg
        JOIN app_user u ON u.id = msg.author_id
        JOIN ticket t ON t.id = msg.ticket_id
        JOIN vehicle v ON v.id = t.vehicle_id
        WHERE u.role = 'client' AND v.user_id <> msg.author_id
        """,
    ),
    Check(
        "active_refresh_token_of_unavailable_user",
        "Действующий refresh-токен у заблокированного или анонимизированного",
        f"""
        SELECT r.id FROM refresh_token r JOIN app_user u ON u.id = r.user_id
        WHERE r.revoked_at IS NULL AND r.expires_at > now() AND {_UNAVAILABLE}
        """,
    ),
    Check(
        "active_push_token_of_ineligible_user",
        "Активный push-токен у пользователя, которому уведомления не положены",
        f"""
        SELECT p.id FROM push_token p JOIN app_user u ON u.id = p.user_id
        WHERE p.revoked_at IS NULL
          AND (u.role <> 'client' OR {_UNAVAILABLE} OR {_NO_ACTIVE_CONSENT})
        """,
    ),
    Check(
        "notification_recipient_not_client",
        "Получатель уведомления — не клиент",
        """
        SELECT r.id FROM notification_recipient r JOIN app_user u ON u.id = r.user_id
        WHERE u.role <> 'client'
        """,
    ),
    Check(
        "vehicle_notification_to_non_owner",
        "Уведомление об авто (напоминание о ТО) получил не владелец авто",
        """
        SELECT r.id FROM notification_recipient r
        JOIN notification n ON n.id = r.notification_id
        JOIN vehicle v ON v.id = n.vehicle_id
        WHERE r.user_id <> v.user_id
        """,
    ),
    Check(
        "reminder_notification_mismatch",
        "Напоминание о ТО не совпадает со своим уведомлением (тип, авто, агрегат)",
        """
        SELECT mr.id FROM maintenance_reminder mr JOIN notification n ON n.id = mr.notification_id
        WHERE n.type <> 'maintenance' OR n.vehicle_id IS DISTINCT FROM mr.vehicle_id
           OR n.aggregate_type_id IS DISTINCT FROM mr.aggregate_type_id
        """,
    ),
    Check(
        "reminder_for_deleted_vehicle",
        "Напоминание о ТО создано после удаления авто",
        """
        SELECT mr.id FROM maintenance_reminder mr JOIN vehicle v ON v.id = mr.vehicle_id
        WHERE v.deleted_at IS NOT NULL AND mr.created_at > v.deleted_at
        """,
    ),
    Check(
        "delivery_to_non_recipient",
        "Доставка push на устройство пользователя, не входящего в получатели уведомления",
        """
        SELECT d.id FROM notification_delivery d JOIN push_token p ON p.id = d.push_token_id
        WHERE NOT EXISTS (
            SELECT 1 FROM notification_recipient r
            WHERE r.notification_id = d.notification_id AND r.user_id = p.user_id)
        """,
    ),
)


@dataclass(frozen=True)
class Violation:
    check: Check
    count: int
    sample: list[int]


def run_checks(db: Session) -> list[Violation]:
    """Нарушения по всем проверкам (пустой список — данные согласованы)."""
    violations = []
    for check in CHECKS:
        ids = [row[0] for row in db.execute(text(f"SELECT id FROM ({check.sql}) q ORDER BY id"))]
        if ids:
            violations.append(Violation(check, len(ids), ids[:SAMPLE]))
    return violations


def main() -> int:
    with get_session_scope()() as db:
        violations = run_checks(db)
    failed = {v.check.name: v for v in violations}
    for check in CHECKS:
        v = failed.get(check.name)
        if v is None:
            print(f"PASS  {check.name}")
        else:
            ids = ", ".join(map(str, v.sample))
            print(f"FAIL  {check.name}: {v.count} — {check.description} (id: {ids})")
    print(f"Проверок: {len(CHECKS)}, с нарушениями: {len(violations)}")
    return 1 if violations else 0


if __name__ == "__main__":
    sys.exit(main())
