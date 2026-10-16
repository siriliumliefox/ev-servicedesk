# Прогон 20261015-163116-peak

## Пороги k6

- PASS `http_req_duration{phase:peak}: p(99)<2000`
- PASS `chat_delivery: p(95)<1000`
- PASS `http_req_duration{kind:write,phase:steady}: p(95)<500`
- PASS `http_req_duration{kind:write,phase:steady}: p(99)<1500`
- PASS `errors{phase:recovery}: rate<0.01`
- PASS `errors{phase:peak}: rate<0.01`
- FAIL `broadcast_delivery_seconds: max<300`
- PASS `http_req_duration{kind:read,phase:steady}: p(95)<300`
- PASS `http_req_duration{kind:read,phase:steady}: p(99)<1000`
- PASS `errors{phase:steady}: rate<0.01`

## Чтение и изменение по фазам

| вид/фаза | requests | p50_ms | p95_ms | p99_ms | max_ms | error_rate |
|---|---|---|---|---|---|---|
| read/peak | 32951 | 4.2 | 15.8 | 38.2 | 114.6 | 0.0 |
| read/recovery | 8851 | 4.6 | 14.0 | 27.6 | 81.2 | 0.0 |
| read/steady | 67407 | 4.7 | 13.6 | 29.4 | 102.4 | 0.0 |
| write/peak | 11298 | 5.5 | 21.9 | 48.3 | 1316.3 | 0.0 |
| write/recovery | 2237 | 7.5 | 22.4 | 47.1 | 81.3 | 0.0 |
| write/steady | 13329 | 8.0 | 23.3 | 45.6 | 132.3 | 0.0 |

## Операции (по убыванию p95)

| операция | requests | p50_ms | p95_ms | p99_ms | max_ms | error_rate |
|---|---|---|---|---|---|---|
| notifications.create | 1 | 1316.3 | 1316.3 | 1316.3 | 1316.3 | 0.0 |
| tickets.create | 820 | 10.5 | 32.9 | 66.2 | 110.6 | 0.0 |
| tickets.messages.create | 16298 | 7.8 | 24.8 | 52.5 | 132.3 | 0.0 |
| tickets.status | 1206 | 8.9 | 24.4 | 49.9 | 104.9 | 0.0 |
| tickets.claim | 2497 | 8.2 | 22.0 | 43.0 | 95.7 | 0.0 |
| tickets.board.new | 4899 | 9.3 | 20.2 | 57.1 | 89.3 | 0.0 |
| notifications.published | 403 | 9.7 | 19.6 | 30.5 | 92.8 | 0.0 |
| tickets.get | 9447 | 6.5 | 19.2 | 48.2 | 102.4 | 0.0289 |
| tickets.board.waiting_vendor | 4899 | 7.5 | 18.3 | 51.1 | 84.9 | 0.0 |
| tickets.board.in_progress | 4899 | 7.7 | 17.9 | 50.8 | 89.8 | 0.0 |
| tickets.board.resolved | 4899 | 7.4 | 17.7 | 50.2 | 94.5 | 0.0 |
| vehicles.mileage | 719 | 5.0 | 15.1 | 42.0 | 89.9 | 0.0 |
| auth.refresh | 930 | 3.9 | 14.4 | 26.8 | 78.9 | 0.0 |
| aggregates.statuses | 15416 | 4.2 | 13.6 | 29.1 | 102.0 | 0.0165 |
| analytics.problem_models | 548 | 6.1 | 13.3 | 17.9 | 46.7 | 0.0 |
| tickets.list.client | 4548 | 4.4 | 12.9 | 34.3 | 94.6 | 0.0 |
| kb.list.admin | 261 | 4.0 | 12.4 | 46.3 | 63.2 | 0.0 |
| tickets.messages.list | 9447 | 3.8 | 12.2 | 22.4 | 94.9 | 0.0289 |
| vehicles.maintenance | 10539 | 3.5 | 12.0 | 25.9 | 114.6 | 0.0241 |
| kb.search | 1880 | 3.9 | 11.6 | 29.2 | 82.0 | 0.0 |
| kb.list | 4275 | 3.4 | 11.0 | 32.0 | 100.8 | 0.0 |
| vehicles.list | 9926 | 3.1 | 10.8 | 20.5 | 102.3 | 0.0 |
| notifications.opened | 2130 | 3.4 | 10.6 | 18.6 | 84.2 | 0.0 |
| uploads.presign | 133 | 2.7 | 10.6 | 15.2 | 25.2 | 0.0 |
| analytics.resolution | 548 | 4.8 | 10.6 | 17.2 | 33.6 | 0.0 |
| notifications.list | 8594 | 3.1 | 10.4 | 27.4 | 90.4 | 0.0 |
| users.list | 245 | 3.6 | 10.3 | 27.6 | 31.8 | 0.0 |
| analytics.conversion | 548 | 3.6 | 9.6 | 15.4 | 54.3 | 0.0 |
| kb.get | 3062 | 2.4 | 9.4 | 30.4 | 81.4 | 0.0 |
| users.me | 9926 | 1.8 | 7.9 | 22.7 | 81.0 | 0.0 |
| s3.put | 0 | nan | nan | nan | nan | 0.0 |
| tickets.ws | 0 | nan | nan | nan | nan | 0.0043 |
| notifications.read | 2130 | 2.1 | 7.9 | 14.7 | 50.4 | 0.0 |

## По минутам

| минута | requests | p50_ms | p95_ms | p99_ms | max_ms | error_rate | rps |
|---|---|---|---|---|---|---|---|
| 0 | 255 | 8.1 | 18.9 | 23.4 | 71.3 | 0.0 | 4.2 |
| 1 | 1190 | 6.4 | 15.6 | 19.9 | 62.5 | 0.0 | 19.8 |
| 2 | 2104 | 5.9 | 15.1 | 21.3 | 45.7 | 0.0019 | 35.1 |
| 3 | 3122 | 5.3 | 13.6 | 20.9 | 58.5 | 0.0077 | 52.0 |
| 4 | 4094 | 5.0 | 13.5 | 28.8 | 59.0 | 0.0093 | 68.2 |
| 5 | 5162 | 5.2 | 14.6 | 29.1 | 59.9 | 0.0124 | 86.0 |
| 6 | 5657 | 5.5 | 16.6 | 39.2 | 82.7 | 0.012 | 94.3 |
| 7 | 5589 | 5.6 | 17.9 | 38.8 | 87.5 | 0.0122 | 93.2 |
| 8 | 5593 | 5.5 | 17.0 | 35.4 | 100.9 | 0.0079 | 93.2 |
| 9 | 5661 | 5.4 | 16.9 | 38.8 | 89.9 | 0.0127 | 94.3 |
| 10 | 7702 | 4.6 | 16.0 | 32.0 | 1316.3 | 0.0061 | 128.4 |
| 11 | 9959 | 4.5 | 19.9 | 44.5 | 110.6 | 0.0041 | 166.0 |
| 12 | 9698 | 4.5 | 18.5 | 46.6 | 114.6 | 0.0055 | 161.6 |
| 13 | 8576 | 4.6 | 17.0 | 36.2 | 101.1 | 0.006 | 142.9 |
| 14 | 8030 | 4.6 | 16.0 | 32.4 | 98.0 | 0.0047 | 133.8 |
| 15 | 5858 | 5.3 | 17.0 | 42.7 | 104.9 | 0.0067 | 97.6 |
| 16 | 5555 | 5.4 | 16.8 | 38.8 | 81.3 | 0.008 | 92.6 |
| 17 | 5605 | 5.4 | 14.8 | 31.3 | 98.2 | 0.0064 | 93.4 |
| 18 | 5496 | 5.4 | 17.7 | 34.2 | 90.6 | 0.0066 | 91.6 |
| 19 | 5697 | 5.2 | 16.2 | 35.6 | 90.3 | 0.0095 | 95.0 |
| 20 | 5637 | 5.7 | 20.3 | 56.4 | 132.3 | 0.0099 | 94.0 |
| 21 | 5185 | 4.9 | 14.5 | 28.7 | 78.3 | 0.0092 | 86.4 |
| 22 | 5175 | 5.2 | 14.4 | 35.0 | 83.8 | 0.0116 | 86.2 |
| 23 | 5098 | 4.9 | 12.9 | 22.1 | 77.9 | 0.0075 | 85.0 |
| 24 | 4012 | 5.2 | 14.1 | 27.6 | 56.2 | 0.007 | 66.9 |
| 25 | 363 | 7.9 | 19.3 | 22.8 | 27.2 | 0.0 | 6.0 |

Чат WebSocket, доставка: {'count': 13890, 'p95': 34, 'p99': 69}

## Контейнеры (максимум)

| сервис | cpu_max_percent | mem_max |
|---|---|---|
| analytics-worker | 0.28 | 51.96MiB |
| backend | 72.43 | 158.4MiB |
| minio | 4.77 | 345.2MiB |
| notifications-worker | 4.18 | 74.04MiB |
| postgres | 117.27 | 158.3MiB |
| redis | 2.14 | 16.79MiB |

## pg_stat_statements, топ-10 по суммарному времени

| calls | total_ms | mean_ms | max_ms | query |
|---|---|---|---|---|
| 5638 | 69450.1 | 12.32 | 1180.2 | `SELECT notification_delivery.id, notification_delivery.notification_id, notification_delivery.push_token_id, notification_delivery.delivered_at, notification_de` |
| 14697 | 9459.9 | 0.64 | 2.9 | `SELECT now() > ticket.sla_due_at AND ticket.status != $1 AS anon_1, (SELECT firmware_release.version FROM firmware_release WHERE firmware_release.id = ticket.fi` |
| 14697 | 7737.7 | 0.53 | 5.4 | `SELECT count(*) AS count_1 FROM (SELECT now() > ticket.sla_due_at AND ticket.status != $1 AS anon_2, (SELECT firmware_release.version FROM firmware_release WHER` |
| 18601 | 3731.7 | 0.20 | 1.0 | `SELECT vehicle.id AS vehicle_id, (SELECT firmware_release.version FROM firmware_release WHERE firmware_release.id = vehicle.current_firmware_release_id) AS anon` |
| 4899 | 2434.2 | 0.50 | 1.7 | `SELECT now() > ticket.sla_due_at AND ticket.status != $1 AS anon_1, (SELECT firmware_release.version FROM firmware_release WHERE firmware_release.id = ticket.fi` |
| 191510 | 2346.9 | 0.01 | 0.7 | `SELECT app_user.id AS app_user_id, app_user.phone AS app_user_phone, app_user.role AS app_user_role, app_user.telegram_id AS app_user_telegram_id, app_user.pass` |
| 4899 | 2081.8 | 0.42 | 2.4 | `SELECT count(*) AS count_1 FROM (SELECT now() > ticket.sla_due_at AND ticket.status != $1 AS anon_2, (SELECT firmware_release.version FROM firmware_release WHER` |
| 16189 | 1234.1 | 0.08 | 1.1 | `INSERT INTO ticket_message (ticket_id, author_id, body, created_at) VALUES ($1::BIGINT, $2::BIGINT, $3::VARCHAR, $4::TIMESTAMP WITH TIME ZONE) RETURNING ticket_` |
| 1 | 1170.1 | 1170.09 | 1170.1 | `INSERT INTO notification_recipient (notification_id, user_id) SELECT $1::BIGINT AS anon_1, anon_2.id FROM (SELECT app_user.id AS id FROM app_user WHERE app_user` |
| 28616 | 689.4 | 0.02 | 1.1 | `SELECT vehicle_aggregate_status.id, vehicle_aggregate_status.vehicle_id, vehicle_aggregate_status.aggregate_type_id, vehicle_aggregate_status.last_replaced_at, ` |
