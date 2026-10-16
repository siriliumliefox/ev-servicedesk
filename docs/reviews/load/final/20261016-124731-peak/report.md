# Прогон 20261016-124731-peak

## Пороги k6

- PASS `http_req_duration{phase:peak}: p(99)<2000`
- PASS `http_req_duration{kind:write,phase:steady}: p(95)<500`
- PASS `http_req_duration{kind:write,phase:steady}: p(99)<1500`
- PASS `http_req_duration{kind:read,phase:steady}: p(99)<1000`
- PASS `http_req_duration{kind:read,phase:steady}: p(95)<300`
- PASS `errors{phase:steady}: rate<0.01`
- PASS `errors{phase:recovery}: rate<0.01`
- PASS `chat_delivery: p(95)<1000`
- PASS `errors{phase:peak}: rate<0.01`

Карточки, взятые другим инженером (ожидаемые 404): 382

Рассылка: 9746 доставок (получателей 10000), последняя за 95 с, половина — за 45 с, в очереди 0

## Чтение и изменение по фазам

| вид/фаза | requests | p50_ms | p95_ms | p99_ms | max_ms | error_rate |
|---|---|---|---|---|---|---|
| read/peak | 32480 | 3.9 | 10.3 | 18.1 | 137.5 | 0.0 |
| read/recovery | 8770 | 4.2 | 9.7 | 15.3 | 66.3 | 0.0 |
| read/steady | 64900 | 4.3 | 10.1 | 15.1 | 106.5 | 0.0 |
| write/peak | 10779 | 5.1 | 14.4 | 25.3 | 1065.4 | 0.0 |
| write/recovery | 2239 | 6.8 | 14.6 | 22.5 | 65.1 | 0.0 |
| write/steady | 10850 | 7.1 | 15.9 | 24.6 | 88.8 | 0.0 |

## Операции (по убыванию p95)

| операция | requests | p50_ms | p95_ms | p99_ms | max_ms | error_rate |
|---|---|---|---|---|---|---|
| notifications.create | 1 | 1065.4 | 1065.4 | 1065.4 | 1065.4 | 0.0 |
| tickets.create | 1028 | 9.4 | 24.4 | 40.4 | 96.2 | 0.0 |
| tickets.status | 1065 | 8.6 | 17.9 | 34.6 | 65.1 | 0.0 |
| notifications.published | 265 | 10.6 | 17.7 | 21.1 | 106.5 | 0.0 |
| tickets.messages.create | 13991 | 6.9 | 15.8 | 24.9 | 126.6 | 0.0 |
| tickets.claim | 1736 | 6.7 | 15.0 | 24.2 | 65.9 | 0.0 |
| tickets.get | 9190 | 6.2 | 13.3 | 19.7 | 93.5 | 0.0 |
| tickets.board.resolved | 4906 | 7.4 | 12.9 | 46.7 | 91.0 | 0.0 |
| tickets.board.waiting_vendor | 4906 | 7.5 | 12.8 | 43.4 | 85.9 | 0.0 |
| kb.list.admin | 259 | 4.0 | 11.0 | 13.9 | 56.4 | 0.0 |
| tickets.board.new | 4906 | 5.5 | 10.8 | 20.3 | 128.4 | 0.0 |
| tickets.board.in_progress | 4906 | 5.4 | 10.4 | 18.5 | 87.4 | 0.0 |
| tickets.list.client | 4356 | 4.4 | 10.3 | 14.2 | 100.0 | 0.0 |
| vehicles.mileage | 746 | 4.5 | 9.8 | 15.1 | 55.7 | 0.0 |
| analytics.problem_models | 519 | 4.9 | 9.8 | 13.6 | 18.8 | 0.0 |
| analytics.resolution | 519 | 4.9 | 9.8 | 13.9 | 49.7 | 0.0 |
| aggregates.statuses | 14393 | 4.2 | 9.7 | 15.3 | 85.4 | 0.0 |
| vehicles.maintenance | 9849 | 3.9 | 9.1 | 14.4 | 116.3 | 0.0 |
| tickets.messages.list | 8808 | 4.0 | 8.7 | 14.1 | 90.5 | 0.0 |
| analytics.conversion | 519 | 4.8 | 8.7 | 11.9 | 25.5 | 0.0 |
| kb.search | 1956 | 3.8 | 8.6 | 13.2 | 67.8 | 0.0 |
| kb.list | 4315 | 3.4 | 8.1 | 11.6 | 65.4 | 0.0 |
| auth.refresh | 922 | 3.4 | 8.0 | 15.8 | 55.4 | 0.0 |
| notifications.list | 8523 | 3.3 | 7.8 | 12.1 | 137.5 | 0.0 |
| notifications.opened | 2129 | 3.1 | 7.8 | 11.9 | 58.1 | 0.0 |
| users.list | 259 | 3.4 | 7.7 | 11.1 | 18.7 | 0.0 |
| uploads.presign | 121 | 2.5 | 7.6 | 27.4 | 31.9 | 0.0 |
| vehicles.list | 9882 | 3.0 | 7.2 | 11.5 | 101.5 | 0.0 |
| kb.get | 3032 | 2.4 | 6.4 | 9.5 | 63.7 | 0.0 |
| users.me | 9882 | 1.6 | 4.7 | 7.8 | 62.1 | 0.0 |
| s3.put | 0 | nan | nan | nan | nan | 0.0 |
| tickets.ws | 0 | nan | nan | nan | nan | 0.0 |
| notifications.read | 2129 | 2.0 | 5.2 | 8.9 | 21.0 | 0.0 |

## По минутам

| минута | requests | p50_ms | p95_ms | p99_ms | max_ms | error_rate | rps |
|---|---|---|---|---|---|---|---|
| 0 | 124 | 7.5 | 17.0 | 22.5 | 28.2 | 0.0 | 2.1 |
| 1 | 720 | 6.9 | 12.6 | 15.5 | 85.9 | 0.0 | 12.0 |
| 2 | 1521 | 6.0 | 12.0 | 16.1 | 77.9 | 0.0 | 25.4 |
| 3 | 2358 | 5.3 | 11.8 | 16.3 | 106.5 | 0.0 | 39.3 |
| 4 | 3170 | 4.7 | 11.0 | 15.8 | 75.6 | 0.0 | 52.8 |
| 5 | 4188 | 4.7 | 11.5 | 19.0 | 69.4 | 0.0 | 69.8 |
| 6 | 5461 | 5.2 | 12.8 | 24.0 | 69.3 | 0.0 | 91.0 |
| 7 | 5405 | 4.7 | 10.4 | 16.0 | 85.4 | 0.0 | 90.1 |
| 8 | 5244 | 4.4 | 9.9 | 14.9 | 61.0 | 0.0 | 87.4 |
| 9 | 4925 | 4.3 | 9.9 | 14.5 | 68.0 | 0.0 | 82.1 |
| 10 | 5969 | 4.5 | 10.9 | 18.7 | 1065.4 | 0.0 | 99.5 |
| 11 | 10014 | 3.7 | 10.4 | 17.5 | 65.9 | 0.0 | 166.9 |
| 12 | 9686 | 4.0 | 11.8 | 21.9 | 137.5 | 0.0 | 161.4 |
| 13 | 8566 | 4.0 | 11.3 | 20.9 | 73.8 | 0.0 | 142.8 |
| 14 | 8065 | 4.4 | 12.4 | 25.3 | 126.6 | 0.0 | 134.4 |
| 15 | 6182 | 4.6 | 10.6 | 16.3 | 73.6 | 0.0 | 103.0 |
| 16 | 5478 | 5.0 | 10.9 | 16.3 | 66.3 | 0.0 | 91.3 |
| 17 | 5561 | 4.9 | 11.3 | 20.1 | 63.9 | 0.0 | 92.7 |
| 18 | 5594 | 4.8 | 12.2 | 22.2 | 88.8 | 0.0 | 93.2 |
| 19 | 5487 | 4.9 | 11.0 | 17.3 | 79.0 | 0.0 | 91.5 |
| 20 | 5514 | 4.7 | 11.0 | 15.9 | 65.7 | 0.0 | 91.9 |
| 21 | 5169 | 4.6 | 10.2 | 15.3 | 73.6 | 0.0 | 86.2 |
| 22 | 5070 | 4.8 | 11.2 | 18.1 | 64.9 | 0.0 | 84.5 |
| 23 | 5119 | 4.4 | 10.1 | 15.9 | 64.4 | 0.0 | 85.3 |
| 24 | 4529 | 4.5 | 10.6 | 16.4 | 67.4 | 0.0 | 75.5 |
| 25 | 899 | 6.5 | 17.6 | 22.0 | 50.5 | 0.0 | 15.0 |
| 26 | 0 | nan | nan | nan | nan | 0.0 | 0.0 |

Чат WebSocket, доставка: {'count': 11706, 'p95': 21, 'p99': 34}

## Контейнеры (максимум)

| сервис | cpu_max_percent | mem_max |
|---|---|---|
| analytics-worker | 0.67 | 51.74MiB |
| backend | 108.66 | 562.1MiB |
| minio | 6.3 | 228.1MiB |
| notifications-worker | 13.76 | 72.07MiB |
| postgres | 53.93 | 275.2MiB |
| redis | 2.04 | 16.43MiB |

## pg_stat_statements, топ-10 по суммарному времени

| calls | total_ms | mean_ms | max_ms | query |
|---|---|---|---|---|
| 14718 | 3200.1 | 0.22 | 2.6 | `SELECT now() > ticket.sla_due_at AND ticket.status != $1 AS anon_1, (SELECT firmware_release.version FROM firmware_release WHERE firmware_release.id = ticket.fi` |
| 14718 | 3151.3 | 0.21 | 2.5 | `SELECT count(*) AS count_1 FROM (SELECT now() > ticket.sla_due_at AND ticket.status != $1 AS anon_2, (SELECT firmware_release.version FROM firmware_release WHER` |
| 175223 | 2679.4 | 0.02 | 3.0 | `SELECT app_user.id AS app_user_id, app_user.phone AS app_user_phone, app_user.role AS app_user_role, app_user.telegram_id AS app_user_telegram_id, app_user.pass` |
| 4906 | 2245.8 | 0.46 | 4.4 | `SELECT now() > ticket.sla_due_at AND ticket.status != $1 AS anon_1, (SELECT firmware_release.version FROM firmware_release WHERE firmware_release.id = ticket.fi` |
| 4906 | 1919.8 | 0.39 | 1.6 | `SELECT count(*) AS count_1 FROM (SELECT now() > ticket.sla_due_at AND ticket.status != $1 AS anon_2, (SELECT firmware_release.version FROM firmware_release WHER` |
| 15758 | 1464.0 | 0.09 | 14.1 | `SELECT notification_delivery.id, notification_delivery.notification_id, notification_delivery.push_token_id, notification_delivery.delivered_at, notification_de` |
| 1846 | 1126.2 | 0.61 | 883.7 | `INSERT INTO notification_delivery (notification_id, push_token_id) SELECT $1::BIGINT AS anon_1, push_token.id FROM push_token WHERE push_token.user_id IN (SELEC` |
| 13590 | 987.6 | 0.07 | 1.9 | `INSERT INTO ticket_message (ticket_id, author_id, body, created_at) VALUES ($1::BIGINT, $2::BIGINT, $3::VARCHAR, $4::TIMESTAMP WITH TIME ZONE) RETURNING ticket_` |
| 519 | 938.7 | 1.81 | 6.5 | `SELECT count(*) AS recipients, count(*) FILTER (WHERE analytics_reminder_fact.opened) AS opened, count(*) FILTER (WHERE analytics_reminder_fact.has_maintenance)` |
| 519 | 866.4 | 1.67 | 3.8 | `SELECT count(*) AS created, count(analytics_ticket_fact.resolution_hours) AS resolved, count(*) FILTER (WHERE analytics_ticket_fact.resolved_overdue) AS overdue` |
