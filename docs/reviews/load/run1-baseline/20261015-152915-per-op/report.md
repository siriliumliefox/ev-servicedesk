# Прогон 20261015-152915-per-op

## Пороги k6


## Чтение и изменение по фазам

| вид/фаза | requests | p50_ms | p95_ms | p99_ms | max_ms | error_rate |
|---|---|---|---|---|---|---|
| read/steady | 48513 | 17.8 | 54.3 | 80.0 | 165.8 | 0.0 |
| write/steady | 13707 | 19.4 | 63.7 | 96.5 | 303.6 | 0.0 |

## Операции (по убыванию p95)

| операция | requests | p50_ms | p95_ms | p99_ms | max_ms | error_rate |
|---|---|---|---|---|---|---|
| tickets.create | 4533 | 33.4 | 82.0 | 125.0 | 205.2 | 0.0 |
| tickets.board.new | 2182 | 30.1 | 81.9 | 106.6 | 125.6 | 0.0 |
| tickets.get | 2323 | 32.0 | 72.4 | 96.1 | 116.0 | 0.0 |
| tickets.board.waiting_vendor | 2182 | 23.0 | 62.7 | 92.6 | 140.2 | 0.0 |
| vehicles.mileage | 2340 | 30.2 | 61.3 | 75.8 | 119.3 | 0.0 |
| aggregates.statuses | 2341 | 25.1 | 60.8 | 85.6 | 107.4 | 0.0 |
| notifications.published | 2340 | 29.9 | 60.0 | 84.3 | 102.7 | 0.0 |
| tickets.board.in_progress | 2182 | 18.7 | 57.6 | 83.4 | 131.3 | 0.0 |
| tickets.list.client | 4663 | 19.5 | 54.6 | 81.8 | 154.8 | 0.0 |
| vehicles.maintenance | 2360 | 18.2 | 51.2 | 87.9 | 110.0 | 0.0 |
| vehicles.list | 2380 | 19.5 | 49.1 | 69.7 | 83.9 | 0.0 |
| users.list | 2360 | 19.3 | 47.9 | 65.7 | 76.7 | 0.0 |
| kb.search | 2363 | 17.2 | 47.3 | 74.5 | 88.2 | 0.0 |
| tickets.board.resolved | 2182 | 10.5 | 46.9 | 74.3 | 108.1 | 0.0 |
| kb.list | 2362 | 17.1 | 46.3 | 85.7 | 115.5 | 0.0 |
| analytics.resolution | 2294 | 13.8 | 43.0 | 66.0 | 80.2 | 0.0 |
| auth.refresh | 4593 | 12.2 | 42.1 | 82.1 | 303.6 | 0.0 |
| tickets.messages.list | 2323 | 13.4 | 40.8 | 56.1 | 165.8 | 0.0 |
| analytics.problem_models | 2294 | 14.4 | 39.9 | 52.8 | 82.8 | 0.0 |
| kb.get | 2362 | 13.1 | 37.5 | 45.7 | 58.7 | 0.0 |
| notifications.list | 2364 | 12.0 | 36.6 | 60.2 | 73.2 | 0.0 |
| users.me | 2362 | 12.2 | 36.2 | 43.8 | 96.2 | 0.0 |
| analytics.conversion | 2294 | 8.7 | 30.1 | 40.7 | 67.4 | 0.0 |
| uploads.presign | 2241 | 7.5 | 25.4 | 45.2 | 88.8 | 0.0 |
| s3.put | 0 | nan | nan | nan | nan | 0.0 |

## По минутам

| минута | requests | p50_ms | p95_ms | p99_ms | max_ms | error_rate | rps |
|---|---|---|---|---|---|---|---|
| 0 | 881 | 13.5 | 34.9 | 39.7 | 44.4 | 0.0 | 14.7 |
| 1 | 1180 | 12.4 | 37.0 | 42.3 | 49.0 | 0.0 | 19.7 |
| 2 | 981 | 18.9 | 50.6 | 75.5 | 96.2 | 0.0 | 16.4 |
| 3 | 1180 | 17.1 | 46.4 | 59.5 | 83.9 | 0.0 | 19.7 |
| 4 | 980 | 20.2 | 60.6 | 83.9 | 92.0 | 0.0 | 16.3 |
| 5 | 1180 | 25.7 | 60.4 | 89.6 | 105.9 | 0.0 | 19.7 |
| 6 | 970 | 27.3 | 61.7 | 102.2 | 107.4 | 0.0 | 16.2 |
| 7 | 1171 | 23.4 | 52.1 | 82.3 | 110.0 | 0.0 | 19.5 |
| 8 | 1000 | 13.9 | 45.9 | 64.7 | 69.5 | 0.0 | 16.7 |
| 9 | 1180 | 11.5 | 35.1 | 44.6 | 51.5 | 0.0 | 19.7 |
| 10 | 1084 | 11.6 | 34.9 | 63.0 | 73.2 | 0.0 | 18.1 |
| 11 | 1075 | 24.3 | 56.8 | 78.0 | 86.4 | 0.0 | 17.9 |
| 12 | 1165 | 24.5 | 56.2 | 76.6 | 118.1 | 0.0 | 19.4 |
| 13 | 1820 | 15.8 | 57.7 | 87.0 | 111.4 | 0.0 | 30.3 |
| 14 | 2346 | 14.8 | 39.1 | 54.0 | 165.8 | 0.0 | 39.1 |
| 15 | 1280 | 16.5 | 48.2 | 81.2 | 92.5 | 0.0 | 21.3 |
| 16 | 1180 | 16.8 | 41.5 | 49.5 | 62.2 | 0.0 | 19.7 |
| 17 | 984 | 15.9 | 45.7 | 96.1 | 115.5 | 0.0 | 16.4 |
| 18 | 1184 | 12.3 | 35.4 | 40.5 | 47.0 | 0.0 | 19.7 |
| 19 | 985 | 16.3 | 43.4 | 79.7 | 88.2 | 0.0 | 16.4 |
| 20 | 1174 | 17.5 | 44.0 | 52.9 | 59.7 | 0.0 | 19.6 |
| 21 | 1020 | 15.9 | 54.1 | 71.0 | 84.8 | 0.0 | 17.0 |
| 22 | 1160 | 31.2 | 61.6 | 86.3 | 119.3 | 0.0 | 19.3 |
| 23 | 1080 | 27.8 | 60.9 | 69.2 | 77.8 | 0.0 | 18.0 |
| 24 | 2080 | 23.9 | 71.4 | 97.5 | 132.5 | 0.0 | 34.7 |
| 25 | 2302 | 18.9 | 55.1 | 68.5 | 89.9 | 0.0 | 38.4 |
| 26 | 2693 | 15.4 | 80.1 | 160.9 | 205.2 | 0.0 | 44.9 |
| 27 | 3339 | 14.3 | 62.1 | 88.5 | 115.8 | 0.0 | 55.6 |
| 28 | 3457 | 18.7 | 66.8 | 100.8 | 303.6 | 0.0 | 57.6 |
| 29 | 4344 | 21.1 | 67.4 | 92.6 | 118.4 | 0.0 | 72.4 |
| 30 | 2321 | 20.2 | 68.1 | 95.6 | 123.7 | 0.0 | 38.7 |
| 31 | 1161 | 29.1 | 69.7 | 95.1 | 116.0 | 0.0 | 19.4 |
| 32 | 1541 | 21.8 | 64.3 | 82.2 | 179.0 | 0.0 | 25.7 |
| 33 | 3438 | 12.3 | 40.3 | 64.4 | 82.8 | 0.0 | 57.3 |
| 34 | 2704 | 12.6 | 40.2 | 57.7 | 85.1 | 0.0 | 45.1 |
| 35 | 1160 | 28.3 | 58.5 | 85.0 | 96.1 | 0.0 | 19.3 |
| 36 | 1080 | 31.0 | 58.9 | 82.4 | 102.7 | 0.0 | 18.0 |
| 37 | 1080 | 17.3 | 49.9 | 67.3 | 74.6 | 0.0 | 18.0 |
| 38 | 1160 | 20.1 | 46.9 | 65.3 | 76.7 | 0.0 | 19.3 |
| 39 | 120 | 25.1 | 39.5 | 47.2 | 49.2 | 0.0 | 2.0 |

Чат WebSocket, доставка: {'count': 0, 'p95': nan, 'p99': nan}

## Контейнеры (максимум)

| сервис | cpu_max_percent | mem_max |
|---|---|---|
| analytics-worker | 0.0 | 51.72MiB |
| backend | 50.4 | 139.5MiB |
| minio | 25.72 | 434.1MiB |
| notifications-worker | 0.51 | 69.22MiB |
| postgres | 17.75 | 146.5MiB |
| redis | 4.33 | 12.49MiB |

## pg_stat_statements, топ-10 по суммарному времени

| calls | total_ms | mean_ms | max_ms | query |
|---|---|---|---|---|
| 6546 | 4072.8 | 0.62 | 3.1 | `SELECT now() > ticket.sla_due_at AND ticket.status != $1 AS anon_1, (SELECT firmware_release.version FROM firmware_release WHERE firmware_release.id = ticket.fi` |
| 2340 | 2739.7 | 1.17 | 2.3 | `SELECT notification.id, notification.type, notification.firmware_release_id, notification.target_vehicle_model_id, notification.vehicle_id, notification.aggrega` |
| 2340 | 2428.0 | 1.04 | 1.8 | `SELECT notification_delivery.notification_id, count(notification_delivery.delivered_at) AS count_1, count(notification_delivery.failed_at) AS count_2, count(not` |
| 6546 | 2304.6 | 0.35 | 4.8 | `SELECT count(*) AS count_1 FROM (SELECT now() > ticket.sla_due_at AND ticket.status != $1 AS anon_2, (SELECT firmware_release.version FROM firmware_release WHER` |
| 4593 | 2277.9 | 0.50 | 211.3 | `SELECT app_user.id FROM app_user WHERE app_user.id = $1::BIGINT FOR NO KEY UPDATE` |
| 2340 | 2102.9 | 0.90 | 1.8 | `SELECT notification_recipient.notification_id, count(*) AS count_1, count(notification_recipient.read_at) AS count_2 FROM notification_recipient WHERE notificat` |
| 2340 | 1893.4 | 0.81 | 2.1 | `SELECT count(*) AS count_1 FROM (SELECT notification.id AS id, notification.type AS type, notification.firmware_release_id AS firmware_release_id, notification.` |
| 2294 | 1401.1 | 0.61 | 1.0 | `SELECT vehicle_model.id, vehicle_model.brand, vehicle_model.model, vehicle_model.trim, vehicle_model.created_at, vehicle_model.updated_at, anon_1.tickets_total,` |
| 64108 | 1329.1 | 0.02 | 0.9 | `SELECT app_user.id AS app_user_id, app_user.phone AS app_user_phone, app_user.role AS app_user_role, app_user.telegram_id AS app_user_telegram_id, app_user.pass` |
| 2294 | 1250.9 | 0.55 | 1.2 | `SELECT count(*) AS created, count(analytics_ticket_fact.resolution_hours) AS resolved, count(*) FILTER (WHERE analytics_ticket_fact.resolved_overdue) AS overdue` |
