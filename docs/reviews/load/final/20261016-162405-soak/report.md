# Прогон 20261016-162405-soak

## Пороги k6

- PASS `checks{scenario:limits}: rate==1`
- PASS `http_req_duration{kind:write,phase:steady}: p(99)<1500`
- PASS `http_req_duration{kind:write,phase:steady}: p(95)<500`
- PASS `errors{phase:steady}: rate<0.01`
- PASS `chat_delivery: p(95)<1000`
- PASS `http_req_duration{kind:read,phase:steady}: p(95)<300`
- PASS `http_req_duration{kind:read,phase:steady}: p(99)<1000`

Карточки, взятые другим инженером (ожидаемые 404): 3903

## Чтение и изменение по фазам

| вид/фаза | requests | p50_ms | p95_ms | p99_ms | max_ms | error_rate |
|---|---|---|---|---|---|---|
| read/steady | 224672 | 4.4 | 11.1 | 102.2 | 1918.5 | 0.0 |
| write/steady | 32269 | 6.9 | 17.3 | 131.4 | 2109.2 | 0.0 |

## Операции (по убыванию p95)

| операция | requests | p50_ms | p95_ms | p99_ms | max_ms | error_rate |
|---|---|---|---|---|---|---|
| tickets.create | 499 | 10.1 | 24.6 | 76.3 | 2109.2 | 0.0 |
| tickets.status | 980 | 8.4 | 18.4 | 49.4 | 1121.0 | 0.0 |
| tickets.messages.create | 23403 | 7.3 | 18.1 | 161.8 | 2067.5 | 0.0 |
| tickets.board.resolved | 12876 | 8.0 | 16.2 | 95.1 | 898.8 | 0.0 |
| tickets.get | 19767 | 6.3 | 14.5 | 126.1 | 1918.5 | 0.0 |
| tickets.board.waiting_vendor | 12876 | 6.1 | 13.4 | 109.5 | 1610.9 | 0.0 |
| tickets.claim | 3193 | 4.4 | 13.2 | 66.5 | 1812.3 | 0.0 |
| notifications.published | 684 | 6.3 | 12.1 | 40.9 | 1071.9 | 0.0 |
| vehicles.mileage | 2059 | 5.0 | 11.7 | 226.6 | 1414.3 | 0.0 |
| aggregates.statuses | 25371 | 4.8 | 11.3 | 120.2 | 1871.6 | 0.0002 |
| tickets.list.client | 11513 | 4.8 | 11.3 | 141.1 | 1564.5 | 0.0 |
| analytics.problem_models | 1386 | 4.7 | 10.7 | 113.9 | 1422.1 | 0.0 |
| vehicles.maintenance | 12737 | 4.4 | 10.4 | 119.4 | 1742.0 | 0.0004 |
| tickets.messages.list | 15864 | 4.5 | 10.4 | 114.1 | 1827.8 | 0.0003 |
| tickets.board.new | 12876 | 4.1 | 10.2 | 99.0 | 1580.4 | 0.0 |
| kb.search | 4986 | 4.0 | 9.9 | 101.4 | 1360.0 | 0.0 |
| users.list | 719 | 3.8 | 9.7 | 171.1 | 413.8 | 0.0 |
| analytics.conversion | 1386 | 4.5 | 9.7 | 54.6 | 1055.9 | 0.0 |
| auth.refresh | 2104 | 3.9 | 9.4 | 21.7 | 696.3 | 0.0 |
| analytics.resolution | 1386 | 4.0 | 9.2 | 92.6 | 1160.8 | 0.0 |
| kb.list | 11514 | 3.7 | 9.2 | 104.5 | 1502.3 | 0.0 |
| kb.list.admin | 707 | 4.3 | 9.1 | 34.7 | 1034.5 | 0.0 |
| notifications.list | 16806 | 3.7 | 8.9 | 107.3 | 1709.2 | 0.0 |
| vehicles.list | 20243 | 3.5 | 8.5 | 98.5 | 1245.7 | 0.0 |
| tickets.board.in_progress | 12876 | 3.5 | 8.4 | 93.5 | 1313.7 | 0.0 |
| kb.get | 7856 | 2.6 | 7.0 | 69.9 | 1400.2 | 0.0 |
| users.me | 20243 | 1.8 | 5.0 | 63.8 | 1290.5 | 0.0 |
| tickets.ws | 0 | nan | nan | nan | nan | 0.0017 |
| uploads.presign | 31 | 3.0 | 6.8 | 11.6 | 11.6 | 0.0 |
| s3.put | 0 | nan | nan | nan | nan | 0.0 |

## По минутам

| минута | requests | p50_ms | p95_ms | p99_ms | max_ms | error_rate | rps |
|---|---|---|---|---|---|---|---|
| 0 | 827 | 6.9 | 17.1 | 22.1 | 101.8 | 0.0 | 13.8 |
| 1 | 2477 | 5.5 | 12.4 | 18.6 | 69.5 | 0.0 | 41.3 |
| 2 | 4159 | 4.8 | 10.2 | 16.1 | 58.7 | 0.0 | 69.3 |
| 3 | 5035 | 4.3 | 8.7 | 12.9 | 76.3 | 0.0 | 83.9 |
| 4 | 4960 | 4.4 | 9.7 | 14.8 | 96.0 | 0.0 | 82.7 |
| 5 | 4802 | 4.4 | 9.7 | 19.3 | 124.1 | 0.0 | 80.0 |
| 6 | 4682 | 4.3 | 9.1 | 12.8 | 69.4 | 0.0 | 78.0 |
| 7 | 4652 | 3.8 | 7.5 | 10.8 | 63.0 | 0.0 | 77.5 |
| 8 | 4426 | 3.9 | 7.9 | 10.6 | 48.8 | 0.0007 | 73.8 |
| 9 | 4166 | 4.0 | 8.0 | 10.9 | 53.9 | 0.0 | 69.4 |
| 10 | 4523 | 4.2 | 8.2 | 11.7 | 49.0 | 0.0 | 75.4 |
| 11 | 4671 | 4.2 | 8.2 | 11.3 | 79.0 | 0.0 | 77.8 |
| 12 | 4732 | 4.1 | 8.2 | 10.7 | 53.7 | 0.0 | 78.9 |
| 13 | 4456 | 4.1 | 8.5 | 11.4 | 46.5 | 0.0 | 74.3 |
| 14 | 4530 | 4.1 | 9.4 | 13.6 | 51.7 | 0.0 | 75.5 |
| 15 | 4226 | 4.4 | 9.1 | 12.5 | 62.8 | 0.0 | 70.4 |
| 16 | 4402 | 4.3 | 8.9 | 12.2 | 50.7 | 0.0 | 73.4 |
| 17 | 4557 | 4.3 | 9.1 | 13.4 | 46.9 | 0.0 | 76.0 |
| 18 | 4295 | 4.3 | 9.1 | 12.9 | 50.2 | 0.0 | 71.6 |
| 19 | 4137 | 4.3 | 9.3 | 13.0 | 43.9 | 0.0 | 69.0 |
| 20 | 4498 | 4.2 | 9.2 | 12.7 | 45.7 | 0.0 | 75.0 |
| 21 | 4368 | 4.2 | 9.2 | 13.4 | 54.1 | 0.0 | 72.8 |
| 22 | 4619 | 4.2 | 9.3 | 13.7 | 47.4 | 0.0 | 77.0 |
| 23 | 4246 | 4.3 | 9.5 | 14.4 | 56.7 | 0.0 | 70.8 |
| 24 | 4019 | 4.4 | 9.9 | 14.2 | 46.8 | 0.0 | 67.0 |
| 25 | 4280 | 4.4 | 9.7 | 14.1 | 68.4 | 0.0 | 71.3 |
| 26 | 4327 | 4.3 | 9.1 | 13.2 | 55.5 | 0.0 | 72.1 |
| 27 | 4406 | 4.3 | 9.0 | 12.3 | 48.9 | 0.0 | 73.4 |
| 28 | 4554 | 4.2 | 9.2 | 12.8 | 46.8 | 0.0 | 75.9 |
| 29 | 4354 | 4.3 | 9.6 | 13.3 | 53.6 | 0.0 | 72.6 |
| 30 | 4605 | 4.2 | 9.5 | 13.9 | 49.7 | 0.0 | 76.8 |
| 31 | 4225 | 4.3 | 9.7 | 13.7 | 56.7 | 0.0 | 70.4 |
| 32 | 4352 | 4.3 | 9.3 | 12.9 | 49.2 | 0.0 | 72.5 |
| 33 | 4164 | 4.3 | 9.4 | 13.2 | 61.3 | 0.0 | 69.4 |
| 34 | 4137 | 4.3 | 10.1 | 15.7 | 50.9 | 0.0 | 69.0 |
| 35 | 4410 | 4.5 | 10.8 | 16.0 | 59.3 | 0.0 | 73.5 |
| 36 | 4347 | 4.6 | 10.0 | 14.2 | 90.1 | 0.0 | 72.5 |
| 37 | 4299 | 6.3 | 17.8 | 32.1 | 102.9 | 0.0 | 71.7 |
| 38 | 4585 | 6.3 | 18.5 | 32.7 | 130.9 | 0.0007 | 76.4 |
| 39 | 4399 | 6.6 | 20.4 | 35.3 | 115.9 | 0.0 | 73.3 |
| 40 | 4505 | 6.7 | 21.3 | 43.9 | 265.3 | 0.0 | 75.1 |
| 41 | 4046 | 5.6 | 14.6 | 24.0 | 157.9 | 0.0 | 67.4 |
| 42 | 4589 | 6.5 | 18.0 | 34.0 | 143.6 | 0.0 | 76.5 |
| 43 | 4342 | 5.1 | 12.9 | 20.3 | 95.6 | 0.0002 | 72.4 |
| 44 | 4218 | 5.0 | 13.1 | 22.1 | 111.4 | 0.0 | 70.3 |
| 45 | 4593 | 5.2 | 13.2 | 21.6 | 93.9 | 0.0 | 76.5 |
| 46 | 4322 | 4.4 | 9.9 | 14.0 | 77.2 | 0.0 | 72.0 |
| 47 | 4098 | 11.1 | 1035.2 | 1610.9 | 2109.2 | 0.0002 | 68.3 |
| 48 | 4260 | 5.4 | 245.8 | 727.6 | 1253.2 | 0.0 | 71.0 |
| 49 | 4336 | 4.8 | 11.1 | 17.0 | 99.4 | 0.0 | 72.3 |
| 50 | 4509 | 4.8 | 11.1 | 18.4 | 90.4 | 0.0013 | 75.2 |
| 51 | 4413 | 4.8 | 10.8 | 15.9 | 94.4 | 0.0 | 73.5 |
| 52 | 4127 | 7.4 | 381.7 | 704.1 | 1121.6 | 0.0005 | 68.8 |
| 53 | 4131 | 4.5 | 10.0 | 14.5 | 64.5 | 0.0 | 68.8 |
| 54 | 4166 | 4.5 | 9.8 | 13.1 | 66.1 | 0.0 | 69.4 |
| 55 | 4107 | 4.7 | 10.7 | 15.2 | 74.9 | 0.0 | 68.5 |
| 56 | 4416 | 4.9 | 10.9 | 16.3 | 99.1 | 0.0 | 73.6 |
| 57 | 4279 | 4.9 | 11.2 | 17.2 | 91.7 | 0.0 | 71.3 |
| 58 | 4224 | 4.8 | 10.8 | 15.4 | 95.2 | 0.0 | 70.4 |
| 59 | 2753 | 5.3 | 12.5 | 17.1 | 63.2 | 0.0 | 45.9 |
| 60 | 340 | 11.6 | 21.7 | 26.7 | 28.4 | 0.0 | 5.7 |
| 61 | 195 | 16.0 | 22.6 | 31.0 | 33.7 | 0.0 | 3.2 |
| 62 | 63 | 16.5 | 42.2 | 79.8 | 79.8 | 0.0 | 1.1 |
| 63 | 0 | nan | nan | nan | nan | 0.0 | 0.0 |

Чат WebSocket, доставка: {'count': 21355, 'p95': 24, 'p99': 224}

## Контейнеры (максимум)

| сервис | cpu_max_percent | mem_max |
|---|---|---|
| analytics-worker | 0.71 | 51.36MiB |
| backend | 227.75 | 540.3MiB |
| minio | 6.58 | 128.6MiB |
| notifications-worker | 11.3 | 71.96MiB |
| postgres | 144.67 | 273MiB |
| redis | 19.81 | 18.48MiB |

## pg_stat_statements, топ-10 по суммарному времени

| calls | total_ms | mean_ms | max_ms | query |
|---|---|---|---|---|
| 12876 | 17099.5 | 1.33 | 33.9 | `SELECT count(*) AS count_1 FROM (SELECT now() > ticket.sla_due_at AND ticket.status != $1 AS anon_2, (SELECT firmware_release.version FROM firmware_release WHER` |
| 12876 | 16606.5 | 1.29 | 36.7 | `SELECT now() > ticket.sla_due_at AND ticket.status != $1 AS anon_1, (SELECT firmware_release.version FROM firmware_release WHERE firmware_release.id = ticket.fi` |
| 18027 | 14054.4 | 0.78 | 1.9 | `SELECT maintenance_reminder.kind FROM maintenance_reminder WHERE maintenance_reminder.vehicle_id = $1::BIGINT AND maintenance_reminder.aggregate_type_id = $2::B` |
| 15283 | 11223.7 | 0.73 | 1.2 | `INSERT INTO notification_delivery (notification_id, push_token_id) SELECT $1::BIGINT AS anon_1, push_token.id FROM push_token WHERE push_token.user_id IN (SELEC` |
| 10012 | 7831.3 | 0.78 | 1.8 | `SELECT maintenance_reminder.kind FROM maintenance_reminder WHERE maintenance_reminder.vehicle_id = $1::BIGINT AND maintenance_reminder.aggregate_type_id = $2::B` |
| 38628 | 7612.3 | 0.20 | 42.9 | `SELECT count(*) AS count_1 FROM (SELECT now() > ticket.sla_due_at AND ticket.status != $1 AS anon_2, (SELECT firmware_release.version FROM firmware_release WHER` |
| 332078 | 6996.5 | 0.02 | 37.4 | `SELECT app_user.id AS app_user_id, app_user.phone AS app_user_phone, app_user.role AS app_user_role, app_user.telegram_id AS app_user_telegram_id, app_user.pass` |
| 38628 | 6253.1 | 0.16 | 39.9 | `SELECT now() > ticket.sla_due_at AND ticket.status != $1 AS anon_1, (SELECT firmware_release.version FROM firmware_release WHERE firmware_release.id = ticket.fi` |
| 12756 | 5359.4 | 0.42 | 1.0 | `INSERT INTO notification_delivery (notification_id, push_token_id) SELECT $1::BIGINT AS anon_1, push_token.id FROM push_token WHERE push_token.user_id IN (SELEC` |
| 24149 | 4646.2 | 0.19 | 25.6 | `SELECT notification_delivery.id, notification_delivery.notification_id, notification_delivery.push_token_id, notification_delivery.delivered_at, notification_de` |
