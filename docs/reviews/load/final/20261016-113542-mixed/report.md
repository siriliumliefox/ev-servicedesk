# Прогон 20261016-113542-mixed

## Пороги k6

- PASS `errors{phase:steady}: rate<0.01`
- PASS `http_req_duration{kind:read,phase:steady}: p(95)<300`
- PASS `http_req_duration{kind:read,phase:steady}: p(99)<1000`
- PASS `chat_delivery: p(95)<1000`
- PASS `checks{scenario:limits}: rate==1`
- PASS `http_req_duration{kind:write,phase:steady}: p(95)<500`
- PASS `http_req_duration{kind:write,phase:steady}: p(99)<1500`

Карточки, взятые другим инженером (ожидаемые 404): 1207

## Чтение и изменение по фазам

| вид/фаза | requests | p50_ms | p95_ms | p99_ms | max_ms | error_rate |
|---|---|---|---|---|---|---|
| read/steady | 73747 | 4.4 | 9.4 | 17.9 | 519.0 | 0.0 |
| write/steady | 10854 | 6.9 | 16.5 | 31.5 | 632.5 | 0.0 |

## Операции (по убыванию p95)

| операция | requests | p50_ms | p95_ms | p99_ms | max_ms | error_rate |
|---|---|---|---|---|---|---|
| tickets.create | 262 | 10.9 | 27.9 | 88.1 | 632.5 | 0.0 |
| tickets.status | 533 | 8.9 | 17.1 | 98.7 | 395.1 | 0.0 |
| tickets.messages.create | 7655 | 7.1 | 16.7 | 33.1 | 346.7 | 0.0 |
| tickets.claim | 1271 | 5.1 | 14.3 | 22.4 | 241.3 | 0.0008 |
| tickets.get | 7045 | 6.3 | 12.2 | 23.7 | 519.0 | 0.0 |
| tickets.board.resolved | 4014 | 7.1 | 11.3 | 24.2 | 250.7 | 0.0 |
| notifications.published | 216 | 6.2 | 10.8 | 15.2 | 18.6 | 0.0 |
| tickets.board.waiting_vendor | 4014 | 5.8 | 10.7 | 47.0 | 194.8 | 0.0 |
| auth.refresh | 500 | 4.3 | 10.4 | 14.4 | 22.2 | 0.0 |
| vehicles.mileage | 618 | 4.9 | 10.3 | 18.5 | 69.1 | 0.0 |
| tickets.board.new | 4014 | 4.3 | 9.7 | 28.4 | 201.5 | 0.0 |
| aggregates.statuses | 8966 | 4.7 | 9.6 | 22.3 | 258.1 | 0.0001 |
| tickets.list.client | 3746 | 4.9 | 9.5 | 18.0 | 270.5 | 0.0 |
| tickets.messages.list | 5838 | 4.8 | 9.1 | 16.5 | 255.3 | 0.0002 |
| kb.list.admin | 230 | 4.3 | 8.9 | 12.7 | 85.5 | 0.0 |
| vehicles.maintenance | 4869 | 4.2 | 8.6 | 21.4 | 220.2 | 0.0002 |
| kb.search | 1565 | 4.1 | 8.3 | 15.7 | 231.7 | 0.0 |
| analytics.resolution | 418 | 3.8 | 8.1 | 11.6 | 68.9 | 0.0 |
| analytics.problem_models | 418 | 4.6 | 8.1 | 12.5 | 106.5 | 0.0 |
| uploads.presign | 15 | 3.1 | 7.7 | 7.7 | 7.7 | 0.0 |
| kb.list | 3561 | 3.7 | 7.7 | 16.1 | 212.8 | 0.0 |
| analytics.conversion | 418 | 4.2 | 7.7 | 10.5 | 71.1 | 0.0 |
| tickets.board.in_progress | 4014 | 3.8 | 7.6 | 12.8 | 420.7 | 0.0 |
| notifications.list | 5193 | 3.6 | 7.5 | 16.3 | 258.9 | 0.0 |
| vehicles.list | 6250 | 3.6 | 7.3 | 13.8 | 225.4 | 0.0 |
| users.list | 228 | 3.9 | 7.2 | 61.8 | 77.1 | 0.0 |
| kb.get | 2480 | 2.6 | 5.7 | 9.9 | 63.4 | 0.0 |
| users.me | 6250 | 1.8 | 4.2 | 7.9 | 165.8 | 0.0 |
| tickets.ws | 0 | nan | nan | nan | nan | 0.0 |
| s3.put | 0 | nan | nan | nan | nan | 0.0 |

## По минутам

| минута | requests | p50_ms | p95_ms | p99_ms | max_ms | error_rate | rps |
|---|---|---|---|---|---|---|---|
| 0 | 118 | 8.2 | 29.4 | 129.3 | 131.6 | 0.0 | 2.0 |
| 1 | 1449 | 6.6 | 15.7 | 22.9 | 109.6 | 0.0 | 24.1 |
| 2 | 3110 | 6.1 | 107.9 | 207.2 | 632.5 | 0.0 | 51.8 |
| 3 | 4786 | 5.0 | 10.9 | 16.9 | 83.7 | 0.0 | 79.8 |
| 4 | 5002 | 5.1 | 11.0 | 19.0 | 104.1 | 0.0 | 83.4 |
| 5 | 4780 | 4.8 | 10.6 | 18.1 | 83.2 | 0.0 | 79.7 |
| 6 | 4758 | 4.5 | 9.1 | 12.3 | 55.1 | 0.0 | 79.3 |
| 7 | 4713 | 4.2 | 8.8 | 12.9 | 62.4 | 0.0 | 78.5 |
| 8 | 4865 | 4.3 | 9.4 | 13.4 | 63.6 | 0.0002 | 81.1 |
| 9 | 4341 | 4.2 | 8.3 | 12.5 | 78.2 | 0.0 | 72.3 |
| 10 | 4107 | 4.2 | 8.5 | 11.8 | 53.6 | 0.0 | 68.5 |
| 11 | 4621 | 4.2 | 8.5 | 11.8 | 66.7 | 0.0 | 77.0 |
| 12 | 4604 | 4.5 | 9.1 | 13.2 | 81.9 | 0.0 | 76.7 |
| 13 | 4606 | 4.9 | 11.0 | 19.2 | 86.7 | 0.0 | 76.8 |
| 14 | 4472 | 4.8 | 11.2 | 19.0 | 92.9 | 0.0 | 74.5 |
| 15 | 4253 | 5.0 | 10.4 | 16.7 | 155.1 | 0.0 | 70.9 |
| 16 | 4628 | 4.7 | 9.9 | 14.2 | 65.0 | 0.0002 | 77.1 |
| 17 | 4682 | 4.4 | 9.1 | 13.0 | 68.3 | 0.0 | 78.0 |
| 18 | 4581 | 4.3 | 8.7 | 11.9 | 58.6 | 0.0004 | 76.3 |
| 19 | 4416 | 4.3 | 9.2 | 13.2 | 53.1 | 0.0 | 73.6 |
| 20 | 1317 | 6.1 | 15.9 | 21.8 | 43.8 | 0.0 | 21.9 |
| 21 | 239 | 14.1 | 22.7 | 25.5 | 30.5 | 0.0 | 4.0 |
| 22 | 130 | 15.3 | 19.9 | 22.6 | 28.9 | 0.0 | 2.2 |
| 23 | 23 | 16.3 | 19.1 | 26.6 | 26.6 | 0.0 | 0.4 |

Чат WebSocket, доставка: {'count': 6394, 'p95': 22, 'p99': 47}

## Контейнеры (максимум)

| сервис | cpu_max_percent | mem_max |
|---|---|---|
| analytics-worker | 1.0 | 51.25MiB |
| backend | 116.68 | 543.1MiB |
| minio | 5.22 | 118.8MiB |
| notifications-worker | 13.2 | 71.65MiB |
| postgres | 81.39 | 235.1MiB |
| redis | 2.48 | 12.5MiB |

## pg_stat_statements, топ-10 по суммарному времени

| calls | total_ms | mean_ms | max_ms | query |
|---|---|---|---|---|
| 18028 | 14680.8 | 0.81 | 4.4 | `SELECT maintenance_reminder.kind FROM maintenance_reminder WHERE maintenance_reminder.vehicle_id = $1::BIGINT AND maintenance_reminder.aggregate_type_id = $2::B` |
| 15284 | 12076.5 | 0.79 | 2.7 | `INSERT INTO notification_delivery (notification_id, push_token_id) SELECT $1::BIGINT AS anon_1, push_token.id FROM push_token WHERE push_token.user_id IN (SELEC` |
| 10012 | 8170.1 | 0.82 | 3.1 | `SELECT maintenance_reminder.kind FROM maintenance_reminder WHERE maintenance_reminder.vehicle_id = $1::BIGINT AND maintenance_reminder.aggregate_type_id = $2::B` |
| 12756 | 5617.3 | 0.44 | 1.6 | `INSERT INTO notification_delivery (notification_id, push_token_id) SELECT $1::BIGINT AS anon_1, push_token.id FROM push_token WHERE push_token.user_id IN (SELEC` |
| 4014 | 5026.2 | 1.25 | 13.3 | `SELECT count(*) AS count_1 FROM (SELECT now() > ticket.sla_due_at AND ticket.status != $1 AS anon_2, (SELECT firmware_release.version FROM firmware_release WHER` |
| 4014 | 4676.8 | 1.17 | 10.6 | `SELECT now() > ticket.sla_due_at AND ticket.status != $1 AS anon_1, (SELECT firmware_release.version FROM firmware_release WHERE firmware_release.id = ticket.fi` |
| 8306 | 3811.3 | 0.46 | 54.7 | `SELECT notification_delivery.id, notification_delivery.notification_id, notification_delivery.push_token_id, notification_delivery.delivered_at, notification_de` |
| 5837 | 2880.0 | 0.49 | 12.7 | `SELECT ticket_message.id, ticket_message.ticket_id, ticket_message.author_id, ticket_message.body, ticket_message.created_at FROM ticket_message WHERE ticket_me` |
| 12042 | 2229.8 | 0.19 | 4.3 | `SELECT count(*) AS count_1 FROM (SELECT now() > ticket.sla_due_at AND ticket.status != $1 AS anon_2, (SELECT firmware_release.version FROM firmware_release WHER` |
| 109267 | 1998.5 | 0.02 | 3.6 | `SELECT app_user.id AS app_user_id, app_user.phone AS app_user_phone, app_user.role AS app_user_role, app_user.telegram_id AS app_user_telegram_id, app_user.pass` |
