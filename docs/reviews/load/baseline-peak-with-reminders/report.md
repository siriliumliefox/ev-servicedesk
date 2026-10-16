# Прогон 20261016-141724-peak

## Пороги k6

- FAIL `errors{phase:peak}: rate<0.01`
- PASS `http_req_duration{kind:write,phase:steady}: p(95)<500`
- FAIL `http_req_duration{kind:write,phase:steady}: p(99)<1500`
- PASS `chat_delivery: p(95)<1000`
- FAIL `errors{phase:steady}: rate<0.01`
- FAIL `http_req_duration{phase:peak}: p(99)<2000`
- FAIL `http_req_duration{kind:read,phase:steady}: p(95)<300`
- FAIL `http_req_duration{kind:read,phase:steady}: p(99)<1000`
- FAIL `errors{phase:recovery}: rate<0.01`

Карточки, взятые другим инженером (ожидаемые 404): 108

## Чтение и изменение по фазам

| вид/фаза | requests | p50_ms | p95_ms | p99_ms | max_ms | error_rate |
|---|---|---|---|---|---|---|
| read/peak | 13999 | 10000.6 | 10003.1 | 10004.6 | 10016.4 | 0.0 |
| read/recovery | 7087 | 0.8 | 633.4 | 5771.1 | 8966.1 | 0.0 |
| read/steady | 51923 | 2.6 | 10000.0 | 10001.7 | 10007.5 | 0.0 |
| write/peak | 3099 | 10000.6 | 10003.1 | 10004.6 | 10007.2 | 0.0 |
| write/recovery | 7610 | 3.1 | 926.2 | 7657.2 | 9371.0 | 0.0 |
| write/steady | 30006 | 3.3 | 15.3 | 10000.8 | 10006.0 | 0.0 |

## Операции (по убыванию p95)

| операция | requests | p50_ms | p95_ms | p99_ms | max_ms | error_rate |
|---|---|---|---|---|---|---|
| uploads.presign | 83 | 10000.3 | 10002.8 | 10004.3 | 10004.3 | 0.988 |
| tickets.create | 1136 | 50.2 | 10002.0 | 10004.0 | 10005.0 | 0.8134 |
| vehicles.maintenance | 5468 | 5.4 | 10001.8 | 10003.7 | 10007.4 | 0.6271 |
| notifications.list | 6978 | 4.0 | 10001.7 | 10003.8 | 10009.9 | 0.761 |
| vehicles.list | 8133 | 3.7 | 10001.6 | 10003.8 | 10008.9 | 0.7489 |
| users.me | 8133 | 2.3 | 10001.6 | 10003.7 | 10008.0 | 0.7489 |
| aggregates.statuses | 9204 | 5.0 | 10001.5 | 10003.6 | 10016.4 | 0.6543 |
| tickets.messages.create | 3134 | 11.2 | 10001.3 | 10003.2 | 10006.0 | 0.2167 |
| notifications.published | 235 | 2.4 | 10001.1 | 10003.1 | 10005.0 | 0.6851 |
| tickets.list.client | 5767 | 1.3 | 10001.1 | 10003.0 | 10007.2 | 0.7902 |
| kb.list | 3403 | 2.2 | 10001.0 | 10002.9 | 10012.8 | 0.6873 |
| kb.search | 1520 | 1.7 | 10001.0 | 10002.7 | 10009.2 | 0.6934 |
| kb.get | 2530 | 1.7 | 10001.0 | 10002.6 | 10005.7 | 0.7075 |
| users.list | 186 | 1.5 | 10001.0 | 10003.4 | 10004.1 | 0.672 |
| analytics.problem_models | 399 | 1.3 | 10001.0 | 10002.9 | 10004.0 | 0.6967 |
| kb.list.admin | 203 | 1.7 | 10001.0 | 10001.9 | 10004.4 | 0.7241 |
| vehicles.mileage | 594 | 1.8 | 10001.0 | 10003.0 | 10004.7 | 0.7508 |
| analytics.resolution | 399 | 1.5 | 10000.9 | 10003.2 | 10004.3 | 0.6967 |
| analytics.conversion | 399 | 1.2 | 10000.9 | 10002.4 | 10003.5 | 0.6967 |
| tickets.board.new | 3746 | 1.7 | 10000.9 | 10002.6 | 10005.9 | 0.6695 |
| tickets.messages.list | 2480 | 5.8 | 10000.8 | 10002.5 | 10005.3 | 0.1266 |
| tickets.board.resolved | 3746 | 1.2 | 10000.8 | 10002.4 | 10008.8 | 0.6695 |
| tickets.board.in_progress | 3746 | 1.4 | 10000.7 | 10002.0 | 10006.1 | 0.6695 |
| tickets.board.waiting_vendor | 3746 | 1.3 | 10000.7 | 10002.2 | 10006.8 | 0.6695 |
| tickets.get | 2588 | 8.3 | 10000.7 | 10001.8 | 10005.4 | 0.1213 |
| auth.refresh | 35070 | 3.2 | 10000.2 | 10001.8 | 10007.2 | 1.0 |
| notifications.create | 1 | 10000.2 | 10000.2 | 10000.2 | 10000.2 | 1.0 |
| notifications.opened | 1 | 376.1 | 376.1 | 376.1 | 376.1 | 0.0 |
| notifications.read | 1 | 241.5 | 241.5 | 241.5 | 241.5 | 0.0 |
| tickets.status | 230 | 10.6 | 39.5 | 10000.6 | 10002.2 | 0.0174 |
| tickets.claim | 465 | 8.2 | 31.6 | 120.4 | 10001.2 | 0.0065 |
| tickets.ws | 0 | nan | nan | nan | nan | 0.7485 |
| s3.put | 0 | nan | nan | nan | nan | 0.0 |

## По минутам

| минута | requests | p50_ms | p95_ms | p99_ms | max_ms | error_rate | rps |
|---|---|---|---|---|---|---|---|
| 0 | 195 | 8.4 | 18.3 | 48.0 | 67.1 | 0.0 | 3.2 |
| 1 | 1098 | 7.1 | 17.0 | 23.0 | 114.6 | 0.0 | 18.3 |
| 2 | 2020 | 5.9 | 13.7 | 20.8 | 109.8 | 0.0 | 33.7 |
| 3 | 2955 | 5.5 | 12.9 | 20.7 | 122.0 | 0.0 | 49.2 |
| 4 | 3747 | 5.0 | 12.1 | 21.3 | 113.7 | 0.0 | 62.5 |
| 5 | 4848 | 5.3 | 27.6 | 149.5 | 367.6 | 0.0 | 80.8 |
| 6 | 5572 | 6.2 | 23.8 | 67.4 | 147.1 | 0.0 | 92.9 |
| 7 | 5341 | 5.7 | 28.8 | 83.2 | 10000.9 | 0.0011 | 89.0 |
| 8 | 3039 | 8.7 | 10001.4 | 10003.5 | 10007.5 | 0.299 | 50.6 |
| 9 | 1799 | 10000.6 | 10003.4 | 10004.9 | 10006.8 | 1.0 | 30.0 |
| 10 | 1783 | 10000.6 | 10003.4 | 10004.7 | 10006.2 | 0.9665 | 29.7 |
| 11 | 3151 | 10000.6 | 10002.8 | 10004.6 | 10016.4 | 0.9595 | 52.5 |
| 12 | 3680 | 10000.7 | 10002.9 | 10004.6 | 10012.8 | 1.0 | 61.3 |
| 13 | 3650 | 10000.6 | 10003.0 | 10004.4 | 10009.2 | 1.0 | 60.8 |
| 14 | 3551 | 10000.7 | 10003.3 | 10004.8 | 10007.2 | 1.0 | 59.2 |
| 15 | 6948 | 279.4 | 10001.6 | 10003.9 | 10007.2 | 0.9989 | 115.8 |
| 16 | 6933 | 1.9 | 6.3 | 11.0 | 388.5 | 1.0 | 115.5 |
| 17 | 6877 | 1.9 | 5.7 | 9.6 | 83.1 | 1.0 | 114.6 |
| 18 | 6693 | 1.9 | 5.8 | 9.5 | 113.1 | 1.0 | 111.5 |
| 19 | 6739 | 1.9 | 5.7 | 8.3 | 67.5 | 1.0 | 112.3 |
| 20 | 6931 | 1.9 | 5.8 | 9.4 | 94.5 | 1.0 | 115.5 |
| 21 | 6724 | 1.9 | 5.5 | 8.6 | 48.0 | 1.0 | 112.1 |
| 22 | 6666 | 2.0 | 5.7 | 9.1 | 79.7 | 1.0 | 111.1 |
| 23 | 6718 | 1.9 | 5.7 | 8.8 | 72.1 | 1.0 | 112.0 |
| 24 | 5498 | 2.0 | 6.4 | 10.2 | 98.1 | 1.0 | 91.6 |
| 25 | 568 | 2.1 | 9.1 | 12.7 | 92.0 | 1.0 | 9.5 |

Чат WebSocket, доставка: {'count': 1849, 'p95': 60, 'p99': 128}

## Контейнеры (максимум)

| сервис | cpu_max_percent | mem_max |
|---|---|---|
| analytics-worker | 1.25 | 51.38MiB |
| backend | 110.11 | 674.2MiB |
| minio | 6.89 | 108.4MiB |
| notifications-worker | 4.63 | 70.3MiB |
| postgres | 81.07 | 240.9MiB |
| redis | 3.81 | 18.35MiB |

## pg_stat_statements, топ-10 по суммарному времени

| calls | total_ms | mean_ms | max_ms | query |
|---|---|---|---|---|
| 164 | 801061.2 | 4884.52 | 80924.7 | `SELECT (SELECT firmware_release.version FROM firmware_release WHERE firmware_release.id = vehicle.current_firmware_release_id) AS anon_1, vehicle.id, vehicle.us` |
| 18029 | 15221.0 | 0.84 | 3.8 | `SELECT maintenance_reminder.kind FROM maintenance_reminder WHERE maintenance_reminder.vehicle_id = $1::BIGINT AND maintenance_reminder.aggregate_type_id = $2::B` |
| 15284 | 12635.3 | 0.83 | 7.5 | `INSERT INTO notification_delivery (notification_id, push_token_id) SELECT $1::BIGINT AS anon_1, push_token.id FROM push_token WHERE push_token.user_id IN (SELEC` |
| 10011 | 8480.1 | 0.85 | 5.2 | `SELECT maintenance_reminder.kind FROM maintenance_reminder WHERE maintenance_reminder.vehicle_id = $1::BIGINT AND maintenance_reminder.aggregate_type_id = $2::B` |
| 12756 | 6187.4 | 0.49 | 3.1 | `INSERT INTO notification_delivery (notification_id, push_token_id) SELECT $1::BIGINT AS anon_1, push_token.id FROM push_token WHERE push_token.user_id IN (SELEC` |
| 2911 | 1930.1 | 0.66 | 43.9 | `SELECT notification_delivery.id, notification_delivery.notification_id, notification_delivery.push_token_id, notification_delivery.delivered_at, notification_de` |
| 4 | 1706.6 | 426.65 | 511.1 | `REFRESH MATERIALIZED VIEW CONCURRENTLY analytics_reminder_fact` |
| 1238 | 1662.3 | 1.34 | 3.8 | `SELECT count(*) AS count_1 FROM (SELECT now() > ticket.sla_due_at AND ticket.status != $1 AS anon_2, (SELECT firmware_release.version FROM firmware_release WHER` |
| 28040 | 1597.4 | 0.06 | 2.4 | `INSERT INTO notification (type, firmware_release_id, target_vehicle_model_id, vehicle_id, aggregate_type_id, message) VALUES ($1, $2::BIGINT, $3::BIGINT, $4::BI` |
| 69064 | 1535.1 | 0.02 | 32.8 | `SELECT app_user.id FROM app_user WHERE app_user.id = $1::BIGINT FOR NO KEY UPDATE` |
