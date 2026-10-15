#!/usr/bin/env python3
"""Данные нагрузочного стенда (глава 24, ADR 0028 п. 6, 7).

Запускается в разовом контейнере из образа-кандидата (load/run.sh): пишет прямо в БД стека
объём, сопоставимый с тестом производительности главы 16, и выпускает токены пользователям —
вход через SMS упирается в лимиты N-06 и A1, а лимиты на стенде такие же, как в production.

  python seed_load.py --out /out/seed.json [--clients 10000]
  python seed_load.py --out /out/seed.json --tokens-only   # новые сессии перед сценарием

Объём при --clients 10000: 10 моделей с двумя прошивками и регламентами на все агрегаты,
10 000 клиентов с согласием ПД, авто, статусами агрегатов и одним push-токеном, 20 инженеров,
3 администратора, 20 000 тикетов за 2 года и 60 000 сообщений, история ТО (замена на каждый
статус агрегата — 60 000, и 8 000 работ), 20 000
напоминаний о ТО, 30 000 доставок push, 200 опубликованных статей базы знаний.

В FILE (0600) — id и токены: у клиента одна сессия, у сотрудника — сотни (виртуальных
пользователей-инженеров больше, чем учётных записей, а refresh-токен одноразовый). Токены
действуют только на этом стенде: подписаны его одноразовым секретом. На экран не выводятся.
При ENVIRONMENT=production сид отказывается работать.
"""

import argparse
import json
import os
import secrets
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.core.db import get_session_scope
from app.core.security import (
    create_access_token,
    hash_password,
    hash_refresh_token,
    new_refresh_token,
)
from app.domain.knowledge.service import create_article, update_article
from app.models.enums import KbArticleType, TicketCategory

EXTRA_MODELS = 7  # к трём моделям из миграции 0006
ENGINEERS = 20
ADMINS = 3
# Сессий у сотрудника — с запасом на номер виртуального пользователя k6 (exec.vu.idInTest):
# у каждого VU своя сессия, иначе ротация одного refresh-токена двумя VU — reuse detection.
ENGINEER_SESSIONS = 100
ADMIN_SESSIONS = 700
ARTICLES = 200
CLIENT_PHONE = "+37533"  # + 7 цифр номера клиента
ENGINEER_PHONE = "+3754400"
ADMIN_PHONE = "+3754499"

# Порядок важен: следующие запросы опираются на строки предыдущих. :clients — число клиентов;
# тикетов — 2 на клиента, сообщений — 3 на тикет. Сейчас «сегодня» — :now.
VOLUME_SQL = [
    """INSERT INTO vehicle_model (brand, model)
       SELECT 'Load', 'M' || lpad(i::text, 2, '0') FROM generate_series(1, :extra_models) i""",
    # По две прошивки на модель: авто на старой, новая — для рассылки о прошивке.
    """INSERT INTO firmware_release (vehicle_model_id, version, released_at)
       SELECT m.id, v.version, v.released_at
       FROM vehicle_model m
       CROSS JOIN (VALUES ('1.0.0', date '2025-01-10'), ('1.1.0', date '2026-09-01'))
            v(version, released_at)
       ON CONFLICT DO NOTHING""",
    # Регламенты на все агрегаты всех моделей: статусы «светофор» считаются, а не «неизвестно».
    """INSERT INTO maintenance_regulation (vehicle_model_id, aggregate_type_id, interval_km,
                                          interval_months)
       SELECT m.id, a.id, 10000 + (a.id % 4) * 5000, 12 + (a.id % 3) * 12
       FROM vehicle_model m CROSS JOIN aggregate_type a
       ON CONFLICT DO NOTHING""",
    """INSERT INTO app_user (phone, role)
       SELECT :client_phone || lpad(i::text, 7, '0'), 'client'
       FROM generate_series(1, :clients) i""",
    """INSERT INTO pd_consent (user_id, policy_version, given_at)
       SELECT id, '1.0', created_at FROM app_user WHERE phone LIKE :client_phone || '%'""",
    """INSERT INTO vehicle (user_id, vehicle_model_id, vin, mileage, current_firmware_release_id)
       SELECT u.id, m.id, 'LDTS' || lpad(u.n::text, 13, '0'), 5000 + (u.n * 7919) % 115000, f.id
       FROM (SELECT id, row_number() OVER (ORDER BY id) n FROM app_user
             WHERE phone LIKE :client_phone || '%') u
       JOIN (SELECT id, row_number() OVER (ORDER BY id) - 1 k, count(*) OVER () total
             FROM vehicle_model) m ON m.k = u.n % m.total
       JOIN firmware_release f ON f.vehicle_model_id = m.id AND f.version = '1.0.0'""",
    # Замены агрегатов: разная выработка — все цвета «светофора».
    """INSERT INTO vehicle_aggregate_status (vehicle_id, aggregate_type_id, last_replaced_at,
                                            last_replaced_mileage)
       SELECT v.id, a.id, (:now)::date - ((v.id * a.id * 37) % 700)::int,
              greatest(v.mileage - ((v.id * a.id * 131) % 25000), 0)
       FROM vehicle v CROSS JOIN aggregate_type a WHERE v.vin LIKE 'LDTS%'""",
    """INSERT INTO push_token (user_id, token)
       SELECT id, 'load-' || id FROM app_user WHERE phone LIKE :client_phone || '%'""",
    """INSERT INTO app_user (phone, role, password_hash)
       SELECT :engineer_phone || lpad(i::text, 5, '0'), 'engineer'::user_role, :password_hash
       FROM generate_series(1, :engineers) i
       UNION ALL
       SELECT :admin_phone || lpad(i::text, 5, '0'), 'admin'::user_role, :password_hash
       FROM generate_series(1, :admins) i""",
    # Тикеты равномерно за 2 года (:clients * 2). Последние 7 дней — открыты (очередь «Новый»
    # и «В работе»), раньше — 90 % решены, 10 % ждут вендора. Срок SLA — по категории.
    """WITH t AS (
         SELECT i, (:now) - (2 * 365 * interval '1 day') * (1 - i::float / (:clients * 2)) AS c,
                (ARRAY['navigation','audio','sim','app_crash','maintenance'])[i % 5 + 1]
                    ::ticket_category AS category
         FROM generate_series(1, :clients * 2) i),
       e AS (SELECT id, row_number() OVER (ORDER BY id) - 1 k FROM app_user WHERE role = 'engineer'
             AND phone LIKE :engineer_phone || '%'),
       v AS (SELECT id, row_number() OVER (ORDER BY id) - 1 k FROM vehicle WHERE vin LIKE 'LDTS%')
       INSERT INTO ticket (vehicle_id, category, status, description, assigned_engineer_id,
                           sla_due_at, first_response_at, resolved_at, created_at)
       SELECT v.id, t.category, s.status, 'Нагрузочный тикет ' || t.i,
              CASE WHEN s.status <> 'new' THEN e.id END,
              t.c + p.resolution_minutes * interval '1 minute',
              CASE WHEN s.status <> 'new' THEN t.c + (t.i % 7 + 1) * interval '17 minutes' END,
              CASE WHEN s.status = 'resolved' THEN t.c + (t.i % 50 + 1) * interval '1 hour' END,
              t.c
       FROM t
       JOIN ticket_sla_policy p ON p.category = t.category
       JOIN v ON v.k = t.i % :clients
       JOIN e ON e.k = t.i % :engineers
       CROSS JOIN LATERAL (SELECT CASE
           WHEN t.c > (:now) - interval '7 days' THEN
             CASE WHEN t.i % 3 = 0 THEN 'new' ELSE 'in_progress' END
           WHEN t.i % 10 = 0 THEN 'waiting_vendor'
           ELSE 'resolved' END::ticket_status AS status) s""",
    # Три сообщения на тикет: клиент, инженер (если тикет взят), снова клиент.
    """INSERT INTO ticket_message (ticket_id, author_id, body, created_at)
       SELECT t.id, CASE WHEN k = 2 AND t.assigned_engineer_id IS NOT NULL
                         THEN t.assigned_engineer_id ELSE v.user_id END,
              'Сообщение ' || k || ' по тикету ' || t.id,
              t.created_at + k * interval '20 minutes'
       FROM ticket t JOIN vehicle v ON v.id = t.vehicle_id
       CROSS JOIN generate_series(1, 3) k
       WHERE v.vin LIKE 'LDTS%'""",
    # История ТО. Замена агрегата пишет и статус, и запись истории (ADR 0016) — на каждую
    # последнюю замену своя запись «замена» (иначе аудит целостности: replacement_without_history).
    """INSERT INTO maintenance_record (vehicle_id, aggregate_type_id, performed_by_user_id,
                                      performed_at, mileage_at_service, kind)
       SELECT s.vehicle_id, s.aggregate_type_id, e.id, s.last_replaced_at,
              s.last_replaced_mileage, 'replacement'
       FROM vehicle_aggregate_status s
       JOIN vehicle v ON v.id = s.vehicle_id AND v.vin LIKE 'LDTS%'
       CROSS JOIN (SELECT min(id) id FROM app_user WHERE phone LIKE :engineer_phone || '%') e
       WHERE s.last_replaced_at IS NOT NULL""",
    # Работы без замены (осмотр, долив) — по тикетам и записанные администратором.
    """INSERT INTO maintenance_record (vehicle_id, aggregate_type_id, performed_by_user_id,
                                      ticket_id, performed_at, mileage_at_service, description)
       SELECT t.vehicle_id, a.id, coalesce(t.assigned_engineer_id, e.id),
              CASE WHEN t.n % 2 = 0 THEN t.id END, t.created_at::date + 1,
              greatest(v.mileage - (t.n * 13) % 20000, 0), 'Осмотр'
       FROM (SELECT id, vehicle_id, assigned_engineer_id, created_at,
                    row_number() OVER (ORDER BY id) n
             FROM ticket WHERE description LIKE 'Нагрузочный тикет %') t
       JOIN vehicle v ON v.id = t.vehicle_id
       JOIN (SELECT id, row_number() OVER (ORDER BY id) - 1 k, count(*) OVER () total
             FROM aggregate_type) a ON a.k = t.n % a.total
       CROSS JOIN (SELECT min(id) id FROM app_user WHERE phone LIKE :engineer_phone || '%') e
       WHERE t.n <= :clients * 4 / 5""",
    # Напоминания о ТО (2 на клиента) с получателями и доставками.
    """WITH n AS (
         INSERT INTO notification (type, vehicle_id, aggregate_type_id, message, created_at)
         SELECT 'maintenance', v.id, a.id, 'Пора заменить расходник',
                (:now) - (2 * 365 * interval '1 day') * (1 - i::float / (:clients * 2))
         FROM generate_series(1, :clients * 2) i
         JOIN (SELECT id, row_number() OVER (ORDER BY id) - 1 k FROM vehicle
               WHERE vin LIKE 'LDTS%') v ON v.k = i % :clients
         JOIN (SELECT id, row_number() OVER (ORDER BY id) - 1 k, count(*) OVER () total
               FROM aggregate_type) a ON a.k = i % a.total
         RETURNING id, vehicle_id, created_at),
       r AS (
         INSERT INTO notification_recipient (notification_id, user_id, read_at, created_at)
         SELECT n.id, v.user_id, CASE WHEN n.id % 3 = 0 THEN n.created_at END, n.created_at
         FROM n JOIN vehicle v ON v.id = n.vehicle_id
         RETURNING notification_id, user_id, created_at)
       INSERT INTO notification_delivery (notification_id, push_token_id, delivered_at,
                                          opened_at, next_attempt_at, created_at)
       SELECT r.notification_id, p.id, r.created_at,
              CASE WHEN r.notification_id % 3 = 0 THEN r.created_at END, r.created_at,
              r.created_at
       FROM r JOIN push_token p ON p.user_id = r.user_id""",
    # Прошлые рассылки о прошивке 1.1.0 — по модели, всем её клиентам (:clients доставок).
    """WITH n AS (
         INSERT INTO notification (type, firmware_release_id, target_vehicle_model_id, message,
                                   created_at)
         SELECT 'firmware', f.id, f.vehicle_model_id, 'Доступна прошивка 1.1.0',
                timestamptz '2026-09-02 10:00+03'
         FROM firmware_release f WHERE f.version = '1.1.0'
         RETURNING id, target_vehicle_model_id, created_at),
       r AS (
         INSERT INTO notification_recipient (notification_id, user_id, created_at)
         SELECT n.id, v.user_id, n.created_at
         FROM n JOIN vehicle v ON v.vehicle_model_id = n.target_vehicle_model_id
         WHERE v.vin LIKE 'LDTS%'
         RETURNING notification_id, user_id, created_at)
       INSERT INTO notification_delivery (notification_id, push_token_id, delivered_at,
                                          next_attempt_at, created_at)
       SELECT r.notification_id, p.id, r.created_at, r.created_at, r.created_at
       FROM r JOIN push_token p ON p.user_id = r.user_id""",
]


def refuse_production(settings: Settings) -> None:
    if settings.environment == "production":
        raise SystemExit("seed_load: ENVIRONMENT=production — нагрузочные данные запрещены")


def seed_volume(db: Session, clients: int, now: datetime) -> None:
    """Объём данных одной транзакцией (без COMMIT): сид стенда и тесты EXPLAIN (ADR 0028 п. 16)."""
    params = {
        "clients": clients,
        "extra_models": EXTRA_MODELS,
        "engineers": ENGINEERS,
        "admins": ADMINS,
        "client_phone": CLIENT_PHONE,
        "engineer_phone": ENGINEER_PHONE,
        "admin_phone": ADMIN_PHONE,
        # Пароль никому не известен: сотрудники стенда входят токенами сида; для сценария
        # лимитов нужен настоящий хэш — неверный пароль даёт 401, а не 500.
        "password_hash": hash_password(secrets.token_urlsafe(24)),
        "now": now,
    }
    for sql in VOLUME_SQL:
        db.execute(text(sql), {k: v for k, v in params.items() if f":{k}" in sql})


def seed_articles(db: Session, count: int) -> None:
    """Опубликованные статьи «руководство» через сервис базы знаний: с версиями, как у админа."""
    categories = list(TicketCategory)
    for i in range(1, count + 1):
        article = create_article(
            db,
            article_type=KbArticleType.GUIDE,
            title=f"Руководство {i}: {categories[i % len(categories)].value}",
            content="Шаг за шагом. " * 60,
            category=categories[i % len(categories)],
            vehicle_model_id=None,
            firmware_release_id=None,
        )
        update_article(db, article.id, {"is_published": True})


def issue_sessions(
    db: Session, settings: Settings, user_ids: list[int], role: str, sessions: int, now: datetime
) -> list[dict[str, Any]]:
    """Пары токенов, как при входе (tokens.issue_pair), — пачкой INSERT, без ORM на 10 000 строк."""
    rows, out = [], []
    expires = now + timedelta(days=settings.refresh_token_ttl_days)
    for user_id in user_ids:
        tokens = []
        for _ in range(sessions):
            refresh = new_refresh_token()
            rows.append({"u": user_id, "h": hash_refresh_token(refresh), "e": expires})
            tokens.append(
                {"access": create_access_token(user_id, role, settings, now), "refresh": refresh}
            )
        out.append({"id": user_id, "sessions": tokens})
    db.execute(
        text("INSERT INTO refresh_token (user_id, token_hash, expires_at) VALUES (:u, :h, :e)"),
        rows,
    )
    return out


def ids(db: Session, sql: str, **params: Any) -> list[int]:
    return list(db.execute(text(sql), params).scalars())


def seed(db: Session, settings: Settings, clients: int) -> dict[str, Any]:
    """Объём данных, статьи и первые сессии."""
    refuse_production(settings)
    seed_volume(db, clients, datetime.now(UTC))
    db.commit()
    seed_articles(db, ARTICLES)
    data = sessions(db, settings)
    db.execute(text("ANALYZE"))
    return data


def sessions(db: Session, settings: Settings) -> dict[str, Any]:
    """Новые сессии всем пользователям сида — перед каждым сценарием (--tokens-only):
    refresh-токены прошлого прогона уже повёрнуты, а access-токен живёт 15 минут.
    """
    refuse_production(settings)
    now = datetime.now(UTC)
    client_rows = db.execute(
        text(
            """SELECT u.id, v.id, v.vehicle_model_id FROM app_user u
               JOIN vehicle v ON v.user_id = u.id AND v.deleted_at IS NULL
               WHERE u.phone LIKE :p || '%' ORDER BY u.id"""
        ),
        {"p": CLIENT_PHONE},
    ).all()
    staff = "SELECT id FROM app_user WHERE phone LIKE :p || '%' ORDER BY id"
    engineers = ids(db, staff, p=ENGINEER_PHONE)
    admins = ids(db, staff, p=ADMIN_PHONE)
    client_sessions = issue_sessions(db, settings, [r[0] for r in client_rows], "client", 1, now)
    data = {
        "issued_at": now.isoformat(),
        "access_ttl_seconds": settings.access_token_ttl_seconds,
        "clients": [
            {"id": r[0], "vehicle_id": r[1], "model_id": r[2], **s["sessions"][0]}
            for r, s in zip(client_rows, client_sessions, strict=True)
        ],
        "engineers": issue_sessions(db, settings, engineers, "engineer", ENGINEER_SESSIONS, now),
        "admins": issue_sessions(db, settings, admins, "admin", ADMIN_SESSIONS, now),
        # Для сценария лимитов: номер сотрудника, на который идут неверные пароли.
        "limits_staff_phone": f"{ENGINEER_PHONE}{ENGINEERS:05d}",
        "articles": ids(
            db,
            "SELECT id FROM knowledge_article WHERE title LIKE 'Руководство %' AND is_published"
            " ORDER BY id",
        ),
        "firmware_new": {
            model: release
            for model, release in db.execute(
                text("SELECT vehicle_model_id, id FROM firmware_release WHERE version = '1.1.0'")
            ).tuples()
        },
    }
    db.commit()
    return data


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--clients", type=int, default=10_000)
    parser.add_argument(
        "--tokens-only", action="store_true", help="только новые сессии для следующего сценария"
    )
    args = parser.parse_args(argv)
    settings = get_settings()
    refuse_production(settings)
    with get_session_scope()() as db:
        data = sessions(db, settings) if args.tokens_only else seed(db, settings, args.clients)
    fd = os.open(args.out, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump(data, f)
    print(
        f"seed_load: клиентов {len(data['clients'])}, инженеров {len(data['engineers'])}, "
        f"администраторов {len(data['admins'])}, статей {len(data['articles'])}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
