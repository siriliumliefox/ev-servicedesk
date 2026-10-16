# Прогон 20261016-115848-peak

## Пороги k6

- PASS `http_req_duration{kind:read,phase:steady}: p(95)<300`
- PASS `http_req_duration{kind:read,phase:steady}: p(99)<1000`
- PASS `http_req_duration{kind:write,phase:steady}: p(95)<500`
- PASS `http_req_duration{kind:write,phase:steady}: p(99)<1500`
- PASS `errors{phase:recovery}: rate<0.01`
- PASS `http_req_duration{phase:peak}: p(99)<2000`
- PASS `errors{phase:steady}: rate<0.01`
- PASS `errors{phase:peak}: rate<0.01`
- PASS `chat_delivery: p(95)<1000`

Карточки, взятые другим инженером (ожидаемые 404): 322

Рассылка: 9829 доставок (получателей 10000), последняя за 98 с, половина — за 46 с, в очереди 0

## Чтение и изменение по фазам

| вид/фаза | requests | p50_ms | p95_ms | p99_ms | max_ms | error_rate |
|---|---|---|---|---|---|---|
| read/peak | 32707 | 4.0 | 10.3 | 24.1 | 328.0 | 0.0 |
| read/recovery | 9026 | 4.2 | 9.7 | 15.0 | 73.7 | 0.0 |
| read/steady | 64855 | 4.6 | 10.5 | 17.0 | 149.1 | 0.0 |
| write/peak | 10777 | 5.4 | 15.2 | 30.6 | 1037.3 | 0.0 |
| write/recovery | 2202 | 7.0 | 15.0 | 21.6 | 76.5 | 0.0 |
| write/steady | 10806 | 7.4 | 16.3 | 26.0 | 115.6 | 0.0 |

## Операции (по убыванию p95)

| операция | requests | p50_ms | p95_ms | p99_ms | max_ms | error_rate |
|---|---|---|---|---|---|---|
| notifications.create | 1 | 1037.3 | 1037.3 | 1037.3 | 1037.3 | 0.0 |
| tickets.create | 960 | 9.8 | 24.3 | 35.9 | 86.5 | 0.0 |
| tickets.status | 1026 | 8.8 | 18.6 | 41.2 | 203.1 | 0.0 |
| tickets.messages.create | 14111 | 7.1 | 16.2 | 26.5 | 398.6 | 0.0 |
| tickets.claim | 1587 | 7.1 | 15.7 | 31.4 | 216.0 | 0.0006 |
| notifications.published | 274 | 8.5 | 15.2 | 30.6 | 82.4 | 0.0 |
| tickets.get | 9213 | 6.4 | 13.7 | 23.5 | 328.0 | 0.0 |
| tickets.board.resolved | 4888 | 7.6 | 13.7 | 38.6 | 295.1 | 0.0 |
| tickets.board.waiting_vendor | 4888 | 7.0 | 13.1 | 47.7 | 152.2 | 0.0 |
| tickets.board.new | 4888 | 5.6 | 11.2 | 24.5 | 268.1 | 0.0 |
| tickets.list.client | 4478 | 4.8 | 10.9 | 16.4 | 189.0 | 0.0 |
| tickets.board.in_progress | 4888 | 5.4 | 10.8 | 24.3 | 147.5 | 0.0 |
| vehicles.mileage | 785 | 4.7 | 10.7 | 16.4 | 85.2 | 0.0 |
| aggregates.statuses | 14705 | 4.4 | 10.2 | 17.5 | 309.0 | 0.0 |
| users.list | 268 | 3.7 | 9.5 | 65.6 | 124.6 | 0.0 |
| kb.list.admin | 279 | 4.0 | 9.5 | 18.7 | 204.0 | 0.0 |
| kb.search | 2021 | 4.0 | 9.4 | 15.2 | 70.3 | 0.0 |
| vehicles.maintenance | 9973 | 4.1 | 9.4 | 17.9 | 296.8 | 0.0 |
| analytics.resolution | 511 | 4.1 | 9.2 | 13.0 | 44.5 | 0.0 |
| analytics.problem_models | 511 | 4.8 | 9.2 | 13.5 | 47.8 | 0.0 |
| notifications.opened | 2129 | 3.6 | 9.2 | 15.4 | 228.6 | 0.0 |
| tickets.messages.list | 8891 | 4.1 | 9.1 | 15.5 | 297.9 | 0.0 |
| analytics.conversion | 511 | 4.7 | 8.8 | 14.6 | 127.9 | 0.0 |
| kb.list | 4245 | 3.5 | 8.4 | 13.6 | 140.1 | 0.0 |
| notifications.list | 8564 | 3.5 | 8.0 | 13.9 | 308.6 | 0.0 |
| vehicles.list | 9795 | 3.3 | 7.8 | 13.4 | 299.8 | 0.0 |
| auth.refresh | 925 | 3.3 | 7.7 | 12.0 | 77.9 | 0.0 |
| kb.get | 3002 | 2.5 | 6.7 | 10.4 | 57.6 | 0.0 |
| notifications.read | 2129 | 2.1 | 5.7 | 12.3 | 196.9 | 0.0 |
| uploads.presign | 132 | 2.5 | 5.0 | 5.4 | 9.8 | 0.0 |
| users.me | 9795 | 1.7 | 4.8 | 9.0 | 201.2 | 0.0 |
| s3.put | 0 | nan | nan | nan | nan | 0.0 |
| tickets.ws | 0 | nan | nan | nan | nan | 0.0014 |

## По минутам

| минута | requests | p50_ms | p95_ms | p99_ms | max_ms | error_rate | rps |
|---|---|---|---|---|---|---|---|
| 0 | 23 | 13.0 | 24.3 | 27.8 | 27.8 | 0.0 | 0.4 |
| 1 | 515 | 7.7 | 13.0 | 15.8 | 98.8 | 0.0 | 8.6 |
| 2 | 1202 | 6.6 | 13.0 | 16.2 | 57.4 | 0.0 | 20.0 |
| 3 | 2219 | 5.5 | 12.1 | 18.2 | 79.8 | 0.0 | 37.0 |
| 4 | 2821 | 5.7 | 13.2 | 18.3 | 111.2 | 0.0 | 47.0 |
| 5 | 3764 | 4.7 | 10.0 | 14.0 | 84.5 | 0.0 | 62.7 |
| 6 | 5441 | 4.9 | 11.8 | 20.9 | 79.8 | 0.0 | 90.7 |
| 7 | 5413 | 5.0 | 11.1 | 17.5 | 84.5 | 0.0 | 90.2 |
| 8 | 5224 | 4.6 | 9.6 | 14.8 | 65.5 | 0.0 | 87.1 |
| 9 | 5046 | 4.4 | 9.8 | 14.9 | 61.9 | 0.0 | 84.1 |
| 10 | 5025 | 4.3 | 9.4 | 13.9 | 1037.3 | 0.0 | 83.8 |
| 11 | 9473 | 4.0 | 10.4 | 17.8 | 71.7 | 0.0001 | 157.9 |
| 12 | 9808 | 4.1 | 14.4 | 129.4 | 398.6 | 0.0 | 163.5 |
| 13 | 9086 | 4.3 | 12.2 | 26.5 | 165.1 | 0.0001 | 151.4 |
| 14 | 8288 | 4.2 | 11.1 | 19.2 | 75.6 | 0.0 | 138.1 |
| 15 | 6765 | 4.5 | 10.6 | 19.6 | 95.2 | 0.0 | 112.8 |
| 16 | 5545 | 5.0 | 11.0 | 17.4 | 76.5 | 0.0 | 92.4 |
| 17 | 5667 | 4.8 | 11.3 | 17.7 | 69.8 | 0.0 | 94.5 |
| 18 | 5583 | 4.8 | 11.3 | 18.4 | 66.1 | 0.0 | 93.0 |
| 19 | 5467 | 4.9 | 11.5 | 19.0 | 80.7 | 0.0 | 91.1 |
| 20 | 5385 | 5.0 | 12.7 | 20.2 | 90.5 | 0.0 | 89.8 |
| 21 | 5455 | 4.8 | 10.3 | 15.1 | 76.2 | 0.0 | 90.9 |
| 22 | 5148 | 4.8 | 10.7 | 18.1 | 70.4 | 0.0 | 85.8 |
| 23 | 5105 | 5.3 | 14.1 | 28.7 | 115.6 | 0.0 | 85.1 |
| 24 | 5000 | 5.7 | 16.4 | 42.4 | 149.1 | 0.0 | 83.3 |
| 25 | 1891 | 5.6 | 14.3 | 17.9 | 77.2 | 0.0 | 31.5 |
| 26 | 14 | 10.9 | 16.4 | 16.4 | 16.4 | 0.0 | 0.2 |

Чат WebSocket, доставка: {'count': 11770, 'p95': 22, 'p99': 38}

## Контейнеры (максимум)

| сервис | cpu_max_percent | mem_max |
|---|---|---|
| analytics-worker | 0.67 | 51.49MiB |
| backend | 110.96 | 552.3MiB |
| minio | 9.77 | 249.2MiB |
| notifications-worker | 11.85 | 72.78MiB |
| postgres | 94.42 | 252.6MiB |
| redis | 2.01 | 13.11MiB |

## pg_stat_statements, топ-10 по суммарному времени

| calls | total_ms | mean_ms | max_ms | query |
|---|---|---|---|---|
| 4888 | 3449.4 | 0.71 | 3.7 | `SELECT count(*) AS count_1 FROM (SELECT now() > ticket.sla_due_at AND ticket.status != $1 AS anon_2, (SELECT firmware_release.version FROM firmware_release WHER` |
| 4888 | 3381.6 | 0.69 | 3.4 | `SELECT now() > ticket.sla_due_at AND ticket.status != $1 AS anon_1, (SELECT firmware_release.version FROM firmware_release WHERE firmware_release.id = ticket.fi` |
| 14664 | 2965.2 | 0.20 | 2.6 | `SELECT now() > ticket.sla_due_at AND ticket.status != $1 AS anon_1, (SELECT firmware_release.version FROM firmware_release WHERE firmware_release.id = ticket.fi` |
| 175831 | 2822.4 | 0.02 | 2.0 | `SELECT app_user.id AS app_user_id, app_user.phone AS app_user_phone, app_user.role AS app_user_role, app_user.telegram_id AS app_user_telegram_id, app_user.pass` |
| 14664 | 2376.6 | 0.16 | 7.5 | `SELECT count(*) AS count_1 FROM (SELECT now() > ticket.sla_due_at AND ticket.status != $1 AS anon_2, (SELECT firmware_release.version FROM firmware_release WHER` |
| 2129 | 1751.5 | 0.82 | 5.3 | `UPDATE notification_delivery SET opened_at=$1::TIMESTAMP WITH TIME ZONE WHERE notification_delivery.notification_id = $2::BIGINT AND notification_delivery.opene` |
| 15806 | 1741.9 | 0.11 | 28.6 | `SELECT notification_delivery.id, notification_delivery.notification_id, notification_delivery.push_token_id, notification_delivery.delivered_at, notification_de` |
| 9795 | 1191.4 | 0.12 | 2.5 | `SELECT count(*) AS count_1 FROM (SELECT (SELECT firmware_release.version FROM firmware_release WHERE firmware_release.id = vehicle.current_firmware_release_id) ` |
| 1805 | 1111.7 | 0.62 | 861.2 | `INSERT INTO notification_delivery (notification_id, push_token_id) SELECT $1::BIGINT AS anon_1, push_token.id FROM push_token WHERE push_token.user_id IN (SELEC` |
| 13736 | 1053.2 | 0.08 | 2.8 | `INSERT INTO ticket_message (ticket_id, author_id, body, created_at) VALUES ($1::BIGINT, $2::BIGINT, $3::VARCHAR, $4::TIMESTAMP WITH TIME ZONE) RETURNING ticket_` |
