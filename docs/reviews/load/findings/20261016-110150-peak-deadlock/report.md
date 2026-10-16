# Прогон 20261016-110150-peak

## Пороги k6

- FAIL `http_req_duration{phase:peak}: p(99)<2000`
- PASS `chat_delivery: p(95)<1000`
- FAIL `http_req_duration{kind:write,phase:steady}: p(95)<500`
- FAIL `http_req_duration{kind:write,phase:steady}: p(99)<1500`
- FAIL `http_req_duration{kind:read,phase:steady}: p(95)<300`
- FAIL `http_req_duration{kind:read,phase:steady}: p(99)<1000`
- FAIL `errors{phase:recovery}: rate<0.01`
- FAIL `errors{phase:steady}: rate<0.01`
- FAIL `errors{phase:peak}: rate<0.01`

Карточки, взятые другим инженером (ожидаемые 404): 244

Рассылка: 9850 доставок (получателей 10000), последняя за 99 с, половина — за 46 с, в очереди 0

## Чтение и изменение по фазам

| вид/фаза | requests | p50_ms | p95_ms | p99_ms | max_ms | error_rate |
|---|---|---|---|---|---|---|
| read/peak | 25812 | 5.3 | 10000.8 | 10002.0 | 10005.5 | 0.0 |
| read/recovery | 3685 | 10000.0 | 10002.9 | 10004.6 | 10008.1 | 0.0 |
| read/steady | 45198 | 5.9 | 10001.5 | 10004.2 | 10034.7 | 0.0 |
| write/peak | 9499 | 7.5 | 10000.9 | 10002.6 | 10008.9 | 0.0 |
| write/recovery | 1243 | 10000.3 | 10002.9 | 10004.6 | 10005.2 | 0.0 |
| write/steady | 6070 | 8.9 | 10001.3 | 10003.8 | 10020.6 | 0.0 |

## Операции (по убыванию p95)

| операция | requests | p50_ms | p95_ms | p99_ms | max_ms | error_rate |
|---|---|---|---|---|---|---|
| auth.refresh | 2426 | 10000.2 | 10002.6 | 10004.5 | 10012.5 | 0.6525 |
| kb.list.admin | 181 | 6.3 | 10002.2 | 10004.1 | 10004.2 | 0.2707 |
| analytics.resolution | 370 | 5.5 | 10002.0 | 10004.2 | 10006.6 | 0.2486 |
| notifications.published | 192 | 9.8 | 10002.0 | 10004.2 | 10004.7 | 0.2917 |
| analytics.problem_models | 370 | 6.3 | 10001.9 | 10004.0 | 10005.2 | 0.2027 |
| analytics.conversion | 370 | 6.0 | 10001.9 | 10005.2 | 10007.2 | 0.1784 |
| kb.get | 2251 | 3.8 | 10001.9 | 10004.6 | 10034.7 | 0.2745 |
| tickets.list.client | 3890 | 7.8 | 10001.9 | 10004.2 | 10017.4 | 0.3211 |
| kb.list | 3252 | 5.2 | 10001.8 | 10004.4 | 10014.9 | 0.2771 |
| vehicles.mileage | 510 | 7.7 | 10001.8 | 10003.5 | 10006.9 | 0.2784 |
| users.me | 7843 | 3.0 | 10001.6 | 10004.2 | 10014.0 | 0.2407 |
| kb.search | 1321 | 5.3 | 10001.5 | 10004.1 | 10006.4 | 0.215 |
| tickets.board.new | 3322 | 7.6 | 10001.4 | 10003.8 | 10010.6 | 0.2116 |
| notifications.list | 7014 | 4.8 | 10001.4 | 10004.2 | 10019.6 | 0.2501 |
| tickets.board.in_progress | 3322 | 5.6 | 10001.3 | 10003.6 | 10026.1 | 0.1701 |
| users.list | 179 | 5.3 | 10001.2 | 10003.8 | 10009.5 | 0.2235 |
| aggregates.statuses | 10160 | 5.6 | 10001.2 | 10003.6 | 10023.6 | 0.1807 |
| vehicles.list | 7819 | 4.7 | 10001.1 | 10003.7 | 10018.0 | 0.1955 |
| tickets.messages.create | 7888 | 9.4 | 10001.1 | 10003.5 | 10020.6 | 0.224 |
| uploads.presign | 126 | 3.8 | 10001.1 | 10003.2 | 10003.4 | 0.1349 |
| tickets.create | 1019 | 12.0 | 10001.0 | 10003.2 | 10004.8 | 0.1305 |
| tickets.board.waiting_vendor | 3322 | 7.7 | 10000.9 | 10003.2 | 10014.5 | 0.1388 |
| tickets.get | 4976 | 7.6 | 10000.9 | 10003.5 | 10017.5 | 0.134 |
| tickets.messages.list | 4732 | 4.9 | 10000.8 | 10003.3 | 10006.7 | 0.1164 |
| vehicles.maintenance | 6490 | 5.1 | 10000.8 | 10003.0 | 10024.5 | 0.1168 |
| tickets.board.resolved | 3319 | 8.7 | 10000.8 | 10003.2 | 10011.0 | 0.1139 |
| tickets.status | 512 | 10.2 | 10000.2 | 10002.1 | 10005.2 | 0.0801 |
| tickets.claim | 888 | 8.6 | 10000.0 | 10001.4 | 10005.0 | 0.0653 |
| s3.put | 0 | nan | nan | nan | nan | 0.0 |
| tickets.ws | 0 | nan | nan | nan | nan | 0.4022 |
| notifications.create | 1 | 1095.2 | 1095.2 | 1095.2 | 1095.2 | 0.0 |
| notifications.opened | 1721 | 4.5 | 14.2 | 264.6 | 10002.6 | 0.0012 |
| notifications.read | 1721 | 2.4 | 8.7 | 241.1 | 10002.2 | 0.0023 |

## По минутам

| минута | requests | p50_ms | p95_ms | p99_ms | max_ms | error_rate | rps |
|---|---|---|---|---|---|---|---|
| 0 | 20 | 12.0 | 21.1 | 25.1 | 25.1 | 0.0 | 0.3 |
| 1 | 540 | 7.7 | 14.1 | 21.6 | 103.5 | 0.0 | 9.0 |
| 2 | 1419 | 6.2 | 13.0 | 17.7 | 82.0 | 0.0 | 23.6 |
| 3 | 2109 | 5.4 | 11.5 | 16.1 | 81.1 | 0.0 | 35.1 |
| 4 | 2814 | 4.9 | 10.7 | 15.8 | 55.7 | 0.0 | 46.9 |
| 5 | 3664 | 4.8 | 11.5 | 19.2 | 115.4 | 0.0 | 61.1 |
| 6 | 5365 | 5.0 | 11.7 | 20.0 | 123.4 | 0.0 | 89.4 |
| 7 | 5284 | 5.5 | 14.3 | 31.7 | 133.3 | 0.0 | 88.1 |
| 8 | 5310 | 4.8 | 10.9 | 19.2 | 177.2 | 0.0 | 88.5 |
| 9 | 5245 | 4.9 | 11.7 | 22.4 | 104.7 | 0.0 | 87.4 |
| 10 | 5014 | 4.8 | 11.2 | 18.8 | 1095.2 | 0.0 | 83.6 |
| 11 | 9358 | 4.9 | 15.8 | 42.9 | 143.9 | 0.0001 | 156.0 |
| 12 | 9900 | 5.0 | 20.2 | 57.0 | 164.6 | 0.0 | 165.0 |
| 13 | 6552 | 5.9 | 10000.8 | 10001.8 | 10004.5 | 0.1627 | 109.2 |
| 14 | 4539 | 10.7 | 10001.4 | 10003.1 | 10005.4 | 0.4612 | 75.7 |
| 15 | 4247 | 10000.0 | 10002.1 | 10004.1 | 10008.9 | 0.5584 | 70.8 |
| 16 | 2661 | 10000.2 | 10002.9 | 10004.5 | 10005.3 | 0.6225 | 44.4 |
| 17 | 2194 | 10000.1 | 10003.0 | 10004.7 | 10008.1 | 0.6381 | 36.6 |
| 18 | 2082 | 10000.2 | 10003.6 | 10007.1 | 10024.5 | 0.6403 | 34.7 |
| 19 | 2048 | 10000.1 | 10003.6 | 10007.6 | 10034.7 | 0.6335 | 34.1 |
| 20 | 2069 | 10000.1 | 10003.0 | 10004.5 | 10005.3 | 0.6257 | 34.5 |
| 21 | 2260 | 9999.2 | 10002.6 | 10004.3 | 10005.8 | 0.5699 | 37.7 |
| 22 | 1916 | 10000.3 | 10004.4 | 10006.5 | 10009.0 | 0.6522 | 31.9 |
| 23 | 1884 | 10000.2 | 10003.8 | 10008.2 | 10026.1 | 0.6383 | 31.4 |
| 24 | 1920 | 10000.2 | 10003.5 | 10004.7 | 10005.5 | 0.6325 | 32.0 |
| 25 | 1069 | 10000.6 | 10004.1 | 10005.5 | 10006.5 | 0.6608 | 17.8 |
| 26 | 24 | 10000.9 | 10003.9 | 10003.9 | 10003.9 | 0.7 | 0.4 |

Чат WebSocket, доставка: {'count': 4799, 'p95': 30, 'p99': 89}

## Контейнеры (максимум)

| сервис | cpu_max_percent | mem_max |
|---|---|---|
| analytics-worker | 1.18 | 51.75MiB |
| backend | 199.64 | 673MiB |
| minio | 3.44 | 216.3MiB |
| notifications-worker | 15.02 | 72.85MiB |
| postgres | 109.44 | 296.9MiB |
| redis | 3.59 | 13.12MiB |

## pg_stat_statements, топ-10 по суммарному времени

| calls | total_ms | mean_ms | max_ms | query |
|---|---|---|---|---|
| 2942 | 2514.7 | 0.85 | 10.0 | `SELECT count(*) AS count_1 FROM (SELECT now() > ticket.sla_due_at AND ticket.status != $1 AS anon_2, (SELECT firmware_release.version FROM firmware_release WHER` |
| 94374 | 2418.6 | 0.03 | 5.3 | `SELECT app_user.id AS app_user_id, app_user.phone AS app_user_phone, app_user.role AS app_user_role, app_user.telegram_id AS app_user_telegram_id, app_user.pass` |
| 2942 | 2414.8 | 0.82 | 32.2 | `SELECT now() > ticket.sla_due_at AND ticket.status != $1 AS anon_1, (SELECT firmware_release.version FROM firmware_release WHERE firmware_release.id = ticket.fi` |
| 1720 | 1980.2 | 1.15 | 12.9 | `UPDATE notification_delivery SET opened_at=$1::TIMESTAMP WITH TIME ZONE WHERE notification_delivery.notification_id = $2::BIGINT AND notification_delivery.opene` |
| 8239 | 1752.0 | 0.21 | 5.0 | `SELECT now() > ticket.sla_due_at AND ticket.status != $1 AS anon_1, (SELECT firmware_release.version FROM firmware_release WHERE firmware_release.id = ticket.fi` |
| 6982 | 1705.7 | 0.24 | 34.4 | `SELECT notification_delivery.id, notification_delivery.notification_id, notification_delivery.push_token_id, notification_delivery.delivered_at, notification_de` |
| 8239 | 1650.7 | 0.20 | 21.1 | `SELECT count(*) AS count_1 FROM (SELECT now() > ticket.sla_due_at AND ticket.status != $1 AS anon_2, (SELECT firmware_release.version FROM firmware_release WHER` |
| 6293 | 1345.3 | 0.21 | 15.6 | `SELECT count(*) AS count_1 FROM (SELECT (SELECT firmware_release.version FROM firmware_release WHERE firmware_release.id = vehicle.current_firmware_release_id) ` |
| 1801 | 1238.9 | 0.69 | 913.1 | `INSERT INTO notification_delivery (notification_id, push_token_id) SELECT $1::BIGINT AS anon_1, push_token.id FROM push_token WHERE push_token.user_id IN (SELEC` |
| 6293 | 982.5 | 0.16 | 51.6 | `SELECT (SELECT firmware_release.version FROM firmware_release WHERE firmware_release.id = vehicle.current_firmware_release_id) AS anon_1, vehicle.id, vehicle.us` |
