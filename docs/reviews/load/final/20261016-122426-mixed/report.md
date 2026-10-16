# Прогон 20261016-122426-mixed

## Пороги k6

- PASS `http_req_duration{kind:write,phase:steady}: p(95)<500`
- PASS `http_req_duration{kind:write,phase:steady}: p(99)<1500`
- PASS `chat_delivery: p(95)<1000`
- PASS `http_req_duration{kind:read,phase:steady}: p(99)<1000`
- PASS `http_req_duration{kind:read,phase:steady}: p(95)<300`
- PASS `checks{scenario:limits}: rate==1`
- PASS `errors{phase:steady}: rate<0.01`

Карточки, взятые другим инженером (ожидаемые 404): 1338

## Чтение и изменение по фазам

| вид/фаза | requests | p50_ms | p95_ms | p99_ms | max_ms | error_rate |
|---|---|---|---|---|---|---|
| read/steady | 72952 | 4.4 | 10.0 | 15.7 | 117.2 | 0.0 |
| write/steady | 10334 | 7.2 | 16.8 | 24.7 | 210.2 | 0.0 |

## Операции (по убыванию p95)

| операция | requests | p50_ms | p95_ms | p99_ms | max_ms | error_rate |
|---|---|---|---|---|---|---|
| tickets.create | 288 | 10.9 | 23.5 | 33.3 | 189.8 | 0.0 |
| tickets.messages.create | 7040 | 7.4 | 17.0 | 24.6 | 166.8 | 0.0 |
| tickets.status | 533 | 9.0 | 16.7 | 25.6 | 46.8 | 0.0 |
| notifications.published | 208 | 9.8 | 14.5 | 20.3 | 80.5 | 0.0 |
| tickets.claim | 1352 | 5.0 | 13.7 | 23.5 | 210.2 | 0.0 |
| tickets.get | 6836 | 6.5 | 13.1 | 21.3 | 97.9 | 0.0 |
| tickets.board.resolved | 4020 | 7.6 | 12.7 | 46.3 | 95.4 | 0.0 |
| tickets.board.waiting_vendor | 4020 | 7.5 | 12.7 | 31.0 | 117.2 | 0.0 |
| uploads.presign | 14 | 3.3 | 11.4 | 11.4 | 11.4 | 0.0 |
| vehicles.mileage | 607 | 5.1 | 10.1 | 13.7 | 53.8 | 0.0 |
| kb.list.admin | 223 | 4.5 | 9.9 | 56.6 | 64.8 | 0.0 |
| tickets.list.client | 3703 | 4.9 | 9.9 | 14.4 | 82.1 | 0.0 |
| aggregates.statuses | 8627 | 4.8 | 9.7 | 14.7 | 85.8 | 0.0 |
| auth.refresh | 500 | 4.2 | 9.6 | 21.3 | 96.3 | 0.0 |
| analytics.conversion | 450 | 5.0 | 9.3 | 14.5 | 66.6 | 0.0 |
| tickets.board.new | 4020 | 4.4 | 9.2 | 15.1 | 95.8 | 0.0 |
| vehicles.maintenance | 4684 | 4.3 | 8.9 | 14.7 | 81.0 | 0.0 |
| tickets.messages.list | 5498 | 4.4 | 8.8 | 14.1 | 95.6 | 0.0 |
| analytics.problem_models | 450 | 5.2 | 8.8 | 12.7 | 35.9 | 0.0 |
| analytics.resolution | 450 | 4.9 | 8.6 | 12.2 | 20.3 | 0.0 |
| kb.search | 1557 | 4.1 | 8.6 | 13.6 | 58.8 | 0.0 |
| kb.list | 3471 | 3.8 | 8.2 | 12.2 | 83.9 | 0.0 |
| notifications.list | 5389 | 3.7 | 8.1 | 11.8 | 64.6 | 0.0 |
| tickets.board.in_progress | 4020 | 4.0 | 8.1 | 12.0 | 92.6 | 0.0 |
| users.list | 191 | 4.0 | 7.4 | 11.6 | 13.1 | 0.0 |
| vehicles.list | 6322 | 3.3 | 7.2 | 11.0 | 96.3 | 0.0 |
| kb.get | 2491 | 2.7 | 6.2 | 9.4 | 93.5 | 0.0 |
| users.me | 6322 | 1.9 | 4.5 | 6.8 | 83.7 | 0.0 |
| s3.put | 0 | nan | nan | nan | nan | 0.0 |
| tickets.ws | 0 | nan | nan | nan | nan | 0.0 |

## По минутам

| минута | requests | p50_ms | p95_ms | p99_ms | max_ms | error_rate | rps |
|---|---|---|---|---|---|---|---|
| 0 | 345 | 7.9 | 16.8 | 21.4 | 30.2 | 0.0 | 5.8 |
| 1 | 1885 | 6.2 | 14.3 | 19.2 | 95.8 | 0.0 | 31.4 |
| 2 | 3559 | 5.3 | 11.2 | 17.3 | 76.3 | 0.0 | 59.3 |
| 3 | 4838 | 4.6 | 10.4 | 16.0 | 76.2 | 0.0 | 80.6 |
| 4 | 4587 | 4.6 | 10.0 | 14.3 | 66.6 | 0.0 | 76.5 |
| 5 | 4583 | 4.6 | 10.2 | 16.8 | 73.5 | 0.0 | 76.4 |
| 6 | 4684 | 5.0 | 14.1 | 42.7 | 210.2 | 0.0 | 78.1 |
| 7 | 4780 | 4.4 | 9.8 | 14.6 | 92.6 | 0.0 | 79.7 |
| 8 | 4737 | 4.5 | 9.5 | 13.1 | 57.9 | 0.0 | 79.0 |
| 9 | 4338 | 4.8 | 10.3 | 14.9 | 81.6 | 0.0 | 72.3 |
| 10 | 4067 | 4.6 | 10.5 | 15.7 | 76.0 | 0.0 | 67.8 |
| 11 | 4467 | 4.6 | 10.4 | 15.5 | 95.4 | 0.0 | 74.5 |
| 12 | 4661 | 4.5 | 10.5 | 16.7 | 90.4 | 0.0 | 77.7 |
| 13 | 4632 | 4.7 | 10.5 | 16.6 | 70.6 | 0.0 | 77.2 |
| 14 | 4801 | 4.7 | 12.3 | 23.1 | 97.9 | 0.0 | 80.0 |
| 15 | 4309 | 4.6 | 10.8 | 18.6 | 94.1 | 0.0 | 71.8 |
| 16 | 4337 | 4.5 | 10.5 | 15.3 | 80.7 | 0.0 | 72.3 |
| 17 | 4701 | 4.7 | 10.7 | 18.0 | 117.2 | 0.0 | 78.3 |
| 18 | 4615 | 4.2 | 9.6 | 13.5 | 63.4 | 0.0 | 76.9 |
| 19 | 3501 | 4.8 | 11.3 | 17.5 | 85.7 | 0.0 | 58.4 |
| 20 | 617 | 8.6 | 19.6 | 24.8 | 68.4 | 0.0 | 10.3 |
| 21 | 168 | 16.7 | 22.6 | 49.4 | 53.3 | 0.0 | 2.8 |
| 22 | 69 | 16.4 | 20.3 | 21.3 | 21.3 | 0.0 | 1.1 |
| 23 | 5 | 17.0 | 18.5 | 18.5 | 18.5 | 0.0 | 0.1 |

Чат WebSocket, доставка: {'count': 5828, 'p95': 23, 'p99': 33}

## Контейнеры (максимум)

| сервис | cpu_max_percent | mem_max |
|---|---|---|
| analytics-worker | 0.34 | 51.73MiB |
| backend | 200.14 | 559.9MiB |
| minio | 7.25 | 140.4MiB |
| notifications-worker | 9.78 | 71.33MiB |
| postgres | 38.44 | 260.2MiB |
| redis | 3.23 | 17.04MiB |

## pg_stat_statements, топ-10 по суммарному времени

| calls | total_ms | mean_ms | max_ms | query |
|---|---|---|---|---|
| 106467 | 2210.8 | 0.02 | 9.3 | `SELECT app_user.id AS app_user_id, app_user.phone AS app_user_phone, app_user.role AS app_user_role, app_user.telegram_id AS app_user_telegram_id, app_user.pass` |
| 12060 | 2038.2 | 0.17 | 1.7 | `SELECT now() > ticket.sla_due_at AND ticket.status != $1 AS anon_1, (SELECT firmware_release.version FROM firmware_release WHERE firmware_release.id = ticket.fi` |
| 12060 | 1802.4 | 0.15 | 2.0 | `SELECT count(*) AS count_1 FROM (SELECT now() > ticket.sla_due_at AND ticket.status != $1 AS anon_2, (SELECT firmware_release.version FROM firmware_release WHER` |
| 4020 | 1777.1 | 0.44 | 1.8 | `SELECT count(*) AS count_1 FROM (SELECT now() > ticket.sla_due_at AND ticket.status != $1 AS anon_2, (SELECT firmware_release.version FROM firmware_release WHER` |
| 4020 | 1746.0 | 0.43 | 2.4 | `SELECT now() > ticket.sla_due_at AND ticket.status != $1 AS anon_1, (SELECT firmware_release.version FROM firmware_release WHERE firmware_release.id = ticket.fi` |
| 450 | 808.2 | 1.80 | 5.6 | `SELECT count(*) AS recipients, count(*) FILTER (WHERE analytics_reminder_fact.opened) AS opened, count(*) FILTER (WHERE analytics_reminder_fact.has_maintenance)` |
| 7339 | 741.3 | 0.10 | 15.3 | `SELECT notification_delivery.id, notification_delivery.notification_id, notification_delivery.push_token_id, notification_delivery.delivered_at, notification_de` |
| 6668 | 623.7 | 0.09 | 7.5 | `INSERT INTO ticket_message (ticket_id, author_id, body, created_at) VALUES ($1::BIGINT, $2::BIGINT, $3::VARCHAR, $4::TIMESTAMP WITH TIME ZONE) RETURNING ticket_` |
| 450 | 616.5 | 1.37 | 3.1 | `SELECT count(*) AS created, count(analytics_ticket_fact.resolution_hours) AS resolved, count(*) FILTER (WHERE analytics_ticket_fact.resolved_overdue) AS overdue` |
| 208 | 587.1 | 2.82 | 34.0 | `SELECT notification_delivery.notification_id, count(notification_delivery.delivered_at) AS count_1, count(notification_delivery.failed_at) AS count_2, count(not` |
