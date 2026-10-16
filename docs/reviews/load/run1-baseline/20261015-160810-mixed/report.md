# Прогон 20261015-160810-mixed

## Пороги k6

- PASS `checks{scenario:limits}: rate==1`
- PASS `http_req_duration{kind:read,phase:steady}: p(95)<300`
- PASS `http_req_duration{kind:read,phase:steady}: p(99)<1000`
- PASS `http_req_duration{kind:write,phase:steady}: p(95)<500`
- PASS `http_req_duration{kind:write,phase:steady}: p(99)<1500`
- PASS `chat_delivery: p(95)<1000`
- FAIL `errors{phase:steady}: rate<0.01`

## Чтение и изменение по фазам

| вид/фаза | requests | p50_ms | p95_ms | p99_ms | max_ms | error_rate |
|---|---|---|---|---|---|---|
| read/steady | 81072 | 4.4 | 12.1 | 22.5 | 200.6 | 0.0 |
| write/steady | 14138 | 7.3 | 20.6 | 36.2 | 215.6 | 0.0 |

## Операции (по убыванию p95)

| операция | requests | p50_ms | p95_ms | p99_ms | max_ms | error_rate |
|---|---|---|---|---|---|---|
| tickets.create | 158 | 13.8 | 28.5 | 60.4 | 92.5 | 0.0 |
| tickets.messages.create | 9936 | 7.2 | 20.8 | 34.7 | 215.6 | 0.0 |
| tickets.claim | 2002 | 7.8 | 19.7 | 45.4 | 98.0 | 0.0 |
| tickets.status | 984 | 8.7 | 19.7 | 39.5 | 55.3 | 0.0 |
| tickets.board.new | 4017 | 9.5 | 18.7 | 46.4 | 129.9 | 0.0 |
| tickets.get | 7926 | 6.3 | 16.0 | 32.0 | 200.6 | 0.037 |
| uploads.presign | 13 | 2.2 | 14.3 | 14.3 | 14.3 | 0.0 |
| tickets.board.in_progress | 4017 | 6.5 | 14.1 | 44.0 | 89.2 | 0.0 |
| notifications.published | 211 | 7.9 | 13.7 | 20.2 | 56.8 | 0.0 |
| vehicles.mileage | 545 | 4.6 | 13.6 | 53.1 | 97.9 | 0.0018 |
| tickets.board.waiting_vendor | 4017 | 6.3 | 13.2 | 28.7 | 75.5 | 0.0 |
| tickets.board.resolved | 4017 | 6.1 | 12.9 | 29.4 | 85.7 | 0.0 |
| analytics.problem_models | 419 | 5.8 | 12.5 | 18.3 | 24.4 | 0.0 |
| aggregates.statuses | 10911 | 4.2 | 11.4 | 21.8 | 137.5 | 0.0256 |
| tickets.list.client | 3735 | 4.3 | 11.2 | 21.7 | 97.5 | 0.0 |
| auth.refresh | 500 | 3.7 | 10.8 | 23.4 | 32.4 | 0.0 |
| users.list | 250 | 3.2 | 10.7 | 15.3 | 41.2 | 0.0 |
| kb.search | 1572 | 3.8 | 10.3 | 28.6 | 70.3 | 0.0 |
| tickets.messages.list | 7926 | 4.0 | 10.2 | 18.1 | 85.7 | 0.037 |
| kb.list.admin | 207 | 3.9 | 10.0 | 30.6 | 46.1 | 0.0 |
| kb.list | 3543 | 3.3 | 9.1 | 18.4 | 51.6 | 0.0 |
| vehicles.maintenance | 6905 | 3.3 | 9.1 | 16.9 | 83.0 | 0.0404 |
| analytics.resolution | 419 | 4.0 | 8.9 | 23.3 | 69.9 | 0.0 |
| analytics.conversion | 419 | 3.5 | 8.7 | 12.4 | 58.1 | 0.0 |
| vehicles.list | 6390 | 2.9 | 8.3 | 14.0 | 77.0 | 0.0 |
| notifications.list | 5333 | 3.0 | 8.3 | 16.8 | 74.1 | 0.0 |
| kb.get | 2448 | 2.2 | 7.1 | 14.5 | 77.1 | 0.0 |
| users.me | 6390 | 1.7 | 6.1 | 13.1 | 63.6 | 0.0 |
| s3.put | 0 | nan | nan | nan | nan | 0.0 |
| tickets.ws | 0 | nan | nan | nan | nan | 0.0 |

## По минутам

| минута | requests | p50_ms | p95_ms | p99_ms | max_ms | error_rate | rps |
|---|---|---|---|---|---|---|---|
| 0 | 688 | 6.4 | 19.6 | 25.0 | 49.6 | 0.0 | 11.5 |
| 1 | 2388 | 5.1 | 14.3 | 21.4 | 49.3 | 0.0059 | 39.8 |
| 2 | 4152 | 4.5 | 12.8 | 18.7 | 57.6 | 0.0135 | 69.2 |
| 3 | 5189 | 4.5 | 12.4 | 21.0 | 64.9 | 0.0108 | 86.5 |
| 4 | 5188 | 4.5 | 12.1 | 20.9 | 53.5 | 0.017 | 86.5 |
| 5 | 5253 | 4.9 | 15.1 | 41.8 | 133.6 | 0.0208 | 87.5 |
| 6 | 5176 | 4.6 | 11.7 | 18.3 | 53.7 | 0.0061 | 86.3 |
| 7 | 5181 | 4.7 | 11.6 | 19.1 | 57.7 | 0.0123 | 86.3 |
| 8 | 5193 | 4.8 | 12.6 | 23.3 | 56.4 | 0.0131 | 86.5 |
| 9 | 5146 | 4.9 | 14.1 | 27.4 | 62.7 | 0.0148 | 85.8 |
| 10 | 5215 | 5.1 | 16.1 | 46.1 | 215.6 | 0.0221 | 86.9 |
| 11 | 5268 | 4.9 | 12.7 | 21.1 | 55.1 | 0.0091 | 87.8 |
| 12 | 5202 | 4.9 | 12.6 | 23.3 | 77.2 | 0.0099 | 86.7 |
| 13 | 5338 | 4.9 | 13.4 | 25.8 | 63.2 | 0.0105 | 89.0 |
| 14 | 5630 | 4.8 | 13.3 | 27.1 | 66.4 | 0.0085 | 93.8 |
| 15 | 5126 | 5.1 | 14.6 | 32.0 | 76.6 | 0.014 | 85.4 |
| 16 | 5167 | 5.1 | 13.7 | 31.2 | 110.4 | 0.0088 | 86.1 |
| 17 | 5153 | 5.1 | 13.6 | 25.6 | 78.5 | 0.0091 | 85.9 |
| 18 | 5270 | 5.0 | 13.8 | 28.3 | 98.0 | 0.0121 | 87.8 |
| 19 | 3588 | 5.5 | 15.3 | 30.3 | 84.1 | 0.0089 | 59.8 |
| 20 | 413 | 14.6 | 26.0 | 32.4 | 52.8 | 0.0 | 6.9 |
| 21 | 209 | 19.7 | 25.8 | 27.5 | 28.9 | 0.0 | 3.5 |
| 22 | 77 | 16.4 | 20.0 | 21.3 | 21.3 | 0.0 | 1.3 |
| 23 | 0 | nan | nan | nan | nan | 0.0 | 0.0 |

Чат WebSocket, доставка: {'count': 7961, 'p95': 27, 'p99': 44}

## Контейнеры (максимум)

| сервис | cpu_max_percent | mem_max |
|---|---|---|
| analytics-worker | 1.4 | 51.96MiB |
| backend | 78.15 | 198.1MiB |
| minio | 9.9 | 266.6MiB |
| notifications-worker | 2.98 | 71.52MiB |
| postgres | 24.07 | 149.8MiB |
| redis | 2.06 | 15.58MiB |

## pg_stat_statements, топ-10 по суммарному времени

| calls | total_ms | mean_ms | max_ms | query |
|---|---|---|---|---|
| 12051 | 7463.5 | 0.62 | 3.2 | `SELECT now() > ticket.sla_due_at AND ticket.status != $1 AS anon_1, (SELECT firmware_release.version FROM firmware_release WHERE firmware_release.id = ticket.fi` |
| 12051 | 5880.1 | 0.49 | 5.2 | `SELECT count(*) AS count_1 FROM (SELECT now() > ticket.sla_due_at AND ticket.status != $1 AS anon_2, (SELECT firmware_release.version FROM firmware_release WHER` |
| 7633 | 2662.0 | 0.35 | 2.6 | `SELECT ticket_message.id, ticket_message.ticket_id, ticket_message.author_id, ticket_message.body, ticket_message.created_at FROM ticket_message WHERE ticket_me` |
| 4017 | 2052.6 | 0.51 | 2.0 | `SELECT count(*) AS count_1 FROM (SELECT now() > ticket.sla_due_at AND ticket.status != $1 AS anon_2, (SELECT firmware_release.version FROM firmware_release WHER` |
| 4017 | 1903.8 | 0.47 | 1.4 | `SELECT now() > ticket.sla_due_at AND ticket.status != $1 AS anon_1, (SELECT firmware_release.version FROM firmware_release WHERE firmware_release.id = ticket.fi` |
| 127801 | 1731.6 | 0.01 | 1.1 | `SELECT app_user.id AS app_user_id, app_user.phone AS app_user_phone, app_user.role AS app_user_role, app_user.telegram_id AS app_user_telegram_id, app_user.pass` |
| 6623 | 1383.2 | 0.21 | 1.2 | `SELECT vehicle.id AS vehicle_id, (SELECT firmware_release.version FROM firmware_release WHERE firmware_release.id = vehicle.current_firmware_release_id) AS anon` |
| 4674 | 766.8 | 0.16 | 0.6 | `SELECT push_token.id, push_token.user_id, push_token.token, push_token.revoked_at, push_token.created_at, push_token.updated_at FROM push_token WHERE push_token` |
| 9905 | 735.2 | 0.07 | 1.0 | `INSERT INTO ticket_message (ticket_id, author_id, body, created_at) VALUES ($1::BIGINT, $2::BIGINT, $3::VARCHAR, $4::TIMESTAMP WITH TIME ZONE) RETURNING ticket_` |
| 21215 | 464.9 | 0.02 | 0.3 | `SELECT vehicle_aggregate_status.id, vehicle_aggregate_status.vehicle_id, vehicle_aggregate_status.aggregate_type_id, vehicle_aggregate_status.last_replaced_at, ` |
