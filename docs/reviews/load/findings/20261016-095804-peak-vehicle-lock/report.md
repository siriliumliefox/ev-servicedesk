# Прогон 20261016-095804-peak

## Пороги k6

- PASS `http_req_duration{phase:peak}: p(99)<2000`
- PASS `errors{phase:peak}: rate<0.01`
- PASS `http_req_duration{kind:read,phase:steady}: p(95)<300`
- PASS `http_req_duration{kind:read,phase:steady}: p(99)<1000`
- PASS `http_req_duration{kind:write,phase:steady}: p(95)<500`
- PASS `http_req_duration{kind:write,phase:steady}: p(99)<1500`
- PASS `errors{phase:steady}: rate<0.01`
- PASS `chat_delivery: p(95)<1000`
- PASS `errors{phase:recovery}: rate<0.01`

Карточки, взятые другим инженером (ожидаемые 404): 480

Рассылка: 9848 доставок (получателей 10000), последняя за 92 с, половина — за 45 с, в очереди 0

## Чтение и изменение по фазам

| вид/фаза | requests | p50_ms | p95_ms | p99_ms | max_ms | error_rate |
|---|---|---|---|---|---|---|
| read/peak | 32720 | 4.0 | 10.3 | 19.8 | 134.0 | 0.0 |
| read/recovery | 8957 | 4.6 | 10.6 | 17.6 | 99.7 | 0.0 |
| read/steady | 64725 | 4.1 | 9.6 | 14.8 | 121.4 | 0.0 |
| write/peak | 10705 | 5.5 | 15.1 | 27.0 | 1069.8 | 0.0 |
| write/recovery | 2205 | 7.6 | 17.6 | 30.9 | 107.2 | 0.0 |
| write/steady | 10967 | 7.1 | 16.1 | 27.6 | 10001.0 | 0.0 |

## Операции (по убыванию p95)

| операция | requests | p50_ms | p95_ms | p99_ms | max_ms | error_rate |
|---|---|---|---|---|---|---|
| notifications.create | 1 | 1069.8 | 1069.8 | 1069.8 | 1069.8 | 0.0 |
| tickets.create | 969 | 9.4 | 25.4 | 47.4 | 112.0 | 0.0 |
| tickets.status | 1070 | 8.6 | 17.8 | 38.2 | 82.7 | 0.0 |
| tickets.messages.create | 14151 | 7.1 | 16.5 | 27.8 | 107.2 | 0.0 |
| tickets.claim | 1628 | 7.1 | 15.3 | 27.0 | 78.6 | 0.0 |
| notifications.published | 286 | 8.1 | 14.3 | 23.4 | 52.2 | 0.0 |
| tickets.get | 9235 | 6.3 | 13.2 | 22.6 | 134.0 | 0.0 |
| tickets.board.resolved | 4908 | 7.5 | 12.9 | 30.7 | 121.4 | 0.0 |
| tickets.board.waiting_vendor | 4908 | 6.9 | 12.4 | 42.9 | 102.2 | 0.0 |
| vehicles.mileage | 757 | 4.7 | 11.2 | 6757.5 | 10001.0 | 0.0079 |
| tickets.board.new | 4908 | 5.2 | 10.8 | 20.0 | 105.6 | 0.0 |
| tickets.board.in_progress | 4908 | 5.0 | 10.3 | 16.9 | 86.8 | 0.0 |
| aggregates.statuses | 14672 | 4.3 | 9.7 | 16.2 | 80.2 | 0.0 |
| tickets.list.client | 4498 | 4.5 | 9.5 | 14.4 | 98.5 | 0.0 |
| notifications.opened | 2129 | 3.7 | 9.1 | 12.8 | 89.3 | 0.0 |
| vehicles.maintenance | 9755 | 3.9 | 9.0 | 15.7 | 118.6 | 0.0 |
| tickets.messages.list | 8755 | 3.9 | 8.8 | 14.3 | 66.9 | 0.0 |
| auth.refresh | 926 | 3.9 | 8.2 | 12.6 | 27.9 | 0.0 |
| analytics.problem_models | 505 | 4.5 | 8.2 | 11.9 | 70.8 | 0.0 |
| kb.search | 1930 | 3.7 | 8.1 | 13.4 | 52.4 | 0.0 |
| uploads.presign | 117 | 2.7 | 7.6 | 15.4 | 16.3 | 0.0 |
| analytics.resolution | 505 | 3.9 | 7.6 | 10.2 | 12.0 | 0.0 |
| analytics.conversion | 505 | 4.1 | 7.5 | 10.9 | 75.1 | 0.0 |
| kb.list.admin | 245 | 3.9 | 7.5 | 13.5 | 72.4 | 0.0 |
| vehicles.list | 9969 | 3.2 | 7.3 | 12.4 | 69.0 | 0.0 |
| notifications.list | 8468 | 3.3 | 7.3 | 11.6 | 90.1 | 0.0 |
| kb.list | 4231 | 3.4 | 7.1 | 10.9 | 110.3 | 0.0 |
| users.list | 261 | 3.5 | 7.0 | 10.3 | 11.8 | 0.0 |
| kb.get | 2981 | 2.4 | 5.9 | 10.3 | 28.7 | 0.0 |
| users.me | 9969 | 1.9 | 5.0 | 8.8 | 84.0 | 0.0 |
| s3.put | 0 | nan | nan | nan | nan | 0.0 |
| tickets.ws | 0 | nan | nan | nan | nan | 0.0028 |
| notifications.read | 2129 | 2.0 | 5.4 | 9.8 | 65.8 | 0.0 |

## По минутам

| минута | requests | p50_ms | p95_ms | p99_ms | max_ms | error_rate | rps |
|---|---|---|---|---|---|---|---|
| 0 | 345 | 7.9 | 13.1 | 18.9 | 21.1 | 0.0 | 5.8 |
| 1 | 1043 | 6.4 | 11.8 | 14.8 | 96.5 | 0.0 | 17.4 |
| 2 | 1860 | 3.3 | 7.1 | 10.6 | 10001.0 | 0.0032 | 31.0 |
| 3 | 2833 | 4.0 | 8.6 | 12.3 | 9404.7 | 0.0 | 47.2 |
| 4 | 3578 | 4.1 | 8.7 | 11.4 | 58.0 | 0.0 | 59.6 |
| 5 | 5040 | 4.4 | 10.0 | 16.4 | 78.6 | 0.0 | 84.0 |
| 6 | 5420 | 4.8 | 11.7 | 20.1 | 85.9 | 0.0 | 90.3 |
| 7 | 5218 | 4.5 | 10.0 | 15.3 | 104.3 | 0.0 | 87.0 |
| 8 | 5187 | 4.5 | 10.4 | 16.0 | 71.1 | 0.0 | 86.5 |
| 9 | 4814 | 4.4 | 10.6 | 16.1 | 61.2 | 0.0 | 80.2 |
| 10 | 8226 | 4.0 | 10.0 | 16.9 | 1069.8 | 0.0 | 137.1 |
| 11 | 9880 | 3.8 | 10.7 | 21.4 | 112.0 | 0.0 | 164.7 |
| 12 | 9321 | 4.2 | 12.5 | 31.9 | 105.9 | 0.0 | 155.3 |
| 13 | 8192 | 4.6 | 12.6 | 23.0 | 134.0 | 0.0 | 136.5 |
| 14 | 7625 | 4.6 | 11.9 | 19.0 | 85.1 | 0.0 | 127.1 |
| 15 | 5689 | 5.4 | 12.9 | 22.7 | 95.0 | 0.0002 | 94.8 |
| 16 | 5566 | 5.3 | 12.7 | 22.3 | 107.2 | 0.0 | 92.8 |
| 17 | 5546 | 5.6 | 15.4 | 36.0 | 110.3 | 0.0 | 92.4 |
| 18 | 5552 | 4.7 | 10.9 | 17.9 | 76.3 | 0.0 | 92.5 |
| 19 | 5414 | 4.7 | 11.2 | 18.8 | 69.9 | 0.0 | 90.2 |
| 20 | 5449 | 4.6 | 10.5 | 15.8 | 78.2 | 0.0002 | 90.8 |
| 21 | 5132 | 4.9 | 11.7 | 18.7 | 121.4 | 0.0 | 85.5 |
| 22 | 5134 | 4.3 | 9.5 | 13.9 | 72.5 | 0.0 | 85.6 |
| 23 | 5072 | 4.2 | 10.3 | 15.9 | 54.0 | 0.0 | 84.5 |
| 24 | 3055 | 4.7 | 12.3 | 18.1 | 52.9 | 0.0 | 50.9 |
| 25 | 88 | 14.9 | 18.6 | 23.1 | 23.1 | 0.0 | 1.5 |

Чат WebSocket, доставка: {'count': 11876, 'p95': 22, 'p99': 40}

## Контейнеры (максимум)

| сервис | cpu_max_percent | mem_max |
|---|---|---|
| analytics-worker | 0.0 | 51.06MiB |
| backend | 77.36 | 288.8MiB |
| minio | 6.1 | 215.8MiB |
| notifications-worker | 47.91 | 287.8MiB |
| postgres | 75.85 | 249.4MiB |
| redis | 1.92 | 12.84MiB |

## pg_stat_statements, топ-10 по суммарному времени

| calls | total_ms | mean_ms | max_ms | query |
|---|---|---|---|---|
| 757 | 254011.5 | 335.55 | 58458.1 | `SELECT (SELECT firmware_release.version FROM firmware_release WHERE firmware_release.id = vehicle.current_firmware_release_id) AS anon_1, vehicle.id, vehicle.us` |
| 17405 | 12783.7 | 0.73 | 2.2 | `SELECT maintenance_reminder.kind FROM maintenance_reminder WHERE maintenance_reminder.vehicle_id = $1::BIGINT AND maintenance_reminder.aggregate_type_id = $2::B` |
| 14348 | 11282.2 | 0.79 | 884.4 | `INSERT INTO notification_delivery (notification_id, push_token_id) SELECT $1::BIGINT AS anon_1, push_token.id FROM push_token WHERE push_token.user_id IN (SELEC` |
| 9698 | 7144.0 | 0.74 | 2.0 | `SELECT maintenance_reminder.kind FROM maintenance_reminder WHERE maintenance_reminder.vehicle_id = $1::BIGINT AND maintenance_reminder.aggregate_type_id = $2::B` |
| 12756 | 5374.6 | 0.42 | 1.8 | `INSERT INTO notification_delivery (notification_id, push_token_id) SELECT $1::BIGINT AS anon_1, push_token.id FROM push_token WHERE push_token.user_id IN (SELEC` |
| 16133 | 4164.7 | 0.26 | 29.6 | `SELECT notification_delivery.id, notification_delivery.notification_id, notification_delivery.push_token_id, notification_delivery.delivered_at, notification_de` |
| 4908 | 3322.6 | 0.68 | 5.2 | `SELECT now() > ticket.sla_due_at AND ticket.status != $1 AS anon_1, (SELECT firmware_release.version FROM firmware_release WHERE firmware_release.id = ticket.fi` |
| 4908 | 3316.6 | 0.68 | 2.7 | `SELECT count(*) AS count_1 FROM (SELECT now() > ticket.sla_due_at AND ticket.status != $1 AS anon_2, (SELECT firmware_release.version FROM firmware_release WHER` |
| 175680 | 2871.8 | 0.02 | 2.3 | `SELECT app_user.id AS app_user_id, app_user.phone AS app_user_phone, app_user.role AS app_user_role, app_user.telegram_id AS app_user_telegram_id, app_user.pass` |
| 14724 | 2801.5 | 0.19 | 4.3 | `SELECT now() > ticket.sla_due_at AND ticket.status != $1 AS anon_1, (SELECT firmware_release.version FROM firmware_release WHERE firmware_release.id = ticket.fi` |
