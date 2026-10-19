# Глава 26 — подготовка production-инфраструктуры: отчёт

Issue #138, PR #142, [ADR 0030](../adr/0030-production-infrastructure.md) (grilling Q1–Q33), глоссарий v1.18.
Статус главы — **PARTIAL**: серверы Timeweb Cloud владелец пока не заказал (решение 2026-10-19). Всё, что
не требует оплаты, сделано и проверено на **локальном стенде** — два «сервера» staging и production из
того же `deploy/`, что пойдёт на ВМ (ADR 0030 п. 23). Серверные шаги включаются секретами и переменными
окружений GitHub без правки кода (`docs/runbooks/OWNER_ACTIONS_26.md`).

## Итог по чек-листу

| Пункт чек-листа | Статус | Доказательство |
|---|---|---|
| Production-серверы/облако и ресурсы | **BLOCKED** (решение владельца: не заказаны) | провайдер, регионы, размеры и цена — ADR 0030 пп. 1–3; `deploy/`, `bootstrap.sh` (проверка — `infra-drill.yml`), `deploy-server.yml` с проверкой «сервер не настроен» |
| Мониторинг (Prometheus/Grafana) и алерты на error rate и падение | PASS (стенд) | 17 целей `up`; 31 правило, `promtool test rules` — PASS (job `infra` в `ci-gate`); дашборды «обзор» и «нагрузка k6» |
| Автоматическое резервное копирование БД и план восстановления | PASS (стенд) | pgBackRest 2.59.3 → S3 по TLS, AES-256 на клиенте, WAL раз в ≤ 60 с, таймеры systemd; `RESTORE.md` |
| План отката | PASS (стенд) | `deploy.sh` (автооткат), страж `rollback_compat.sh` в cd-staging (мутация поймана), `ROLLBACK.md` |
| Централизованный сбор логов (ELK/Loki) | PASS (стенд), Loki + Alloy | журналы всех 17 сервисов с метками `env`, `service`, `logger`, `level`; `app.security` — 365 дней |
| Учебное восстановление (DR drill) | PASS (стенд) | RPO 33 с (цель ≤ 300), RTO 22 с (цель ≤ 7200), аудит — 0 нарушений; `restore-check` — PASS |
| Тест алертов: сбой → уведомление в целевое время | PASS (стенд): приёмник и Telegram владельца | 6 сценариев, critical за 101–180 с (цель ≤ 300); Telegram — 167/197 с, «восстановлено» доставлено |
| **DoD:** production готов | **BLOCKED** | серверов нет |
| **DoD:** мониторинг и алерты работают | PASS (стенд) | см. выше |
| **DoD:** план отката опробован на staging | PASS на staging стенда; на сервере — BLOCKED | учение отката, ниже |

Протоколы учений и ZAP — `docs/reviews/infra/` (откат, DR, алерты, ZAP).

## Стенд (ADR 0030 п. 23)
`scripts/infra_stack.sh` на Mac (Docker Desktop, 15 ядер, 8 ГБ): провайдер (MinIO с TLS вместо S3 Timeweb,
реестр образов вместо ghcr, приёмник алертов вместо Telegram и dead-man), окружения `ev-staging` и
`ev-production` — по 17 контейнеров, ≈ 1,3 ГБ памяти на холостом ходу. Выкладка — тем же путём, что на ВМ:
`make-bundle.sh` → `deploy.sh receive` (миграции → up → smoke через nginx и TLS → автооткат).

Отличия от ВМ: один Docker на оба окружения; S3 — MinIO; «production» стенда работает в режиме staging
(A1 и FCM недоступны — фейковые SMS и push); TLS — свой УЦ; Let's Encrypt, firewall Timeweb и ufw не
проверяются стендом (`bootstrap.sh` — `infra-drill.yml` на Ubuntu 24.04).

## Учение отката (2026-10-19, staging стенда)
| Шаг | Результат |
|---|---|
| выпуск N = `d3257fb` (глава 24, схема 0015) на новую «ВМ» | включён за 23 с, клиент вошёл, `/v1/vehicles` = 200 |
| N+1 = рабочее дерево (миграции 0016–0017) | включён за 13 с, схема 0017 |
| откат N+1 → N **без downgrade** | 11 с; образ N работает на схеме 0017, сессия клиента N сохранилась |
| снова N+1 | 13 с |
| выпуск с неверными настройками (`SMS_PROVIDER`) | отклонён на миграциях за 2 с, работающий не тронут |
| выпуск без бакета S3 (ошибка видна только при старте API) | переключён → backend перезапускается при старте → **автооткат** на N+1 за **20 с** (до правки F7 — 208 с) |

Страж в cd-staging (`scripts/rollback_compat.sh`): N на схеме кандидата — PASS (preflight, `/health`, 401,
ORM читает все 25 таблиц, аудит целостности); мутация `DROP COLUMN app_user.telegram_id` — FAIL «ORM
предыдущего выпуска не читает схему кандидата» (страж ловит несовместимую миграцию).

Наблюдение: access-токены выпуска до главы 25 после обновления не принимаются (с главы 25 обязателен
`iat_ms`) — клиент один раз получает 401 и обновляет пару refresh-токеном; новый токен — 200.

## Учебное восстановление (2026-10-19, staging стенда)
Пульс — запись в `ops.dr_pulse` раз в 2 с; полный бэкап; через 90 с — **авария**: SIGKILL всех процессов
(PostgreSQL не успевает отправить текущий сегмент WAL), удаление контейнеров, томов и каталога
окружения. «Новая ВМ»: каталог окружения, `deploy.sh receive` без включения, `restore.sh`.

| Показатель | Цель | Факт |
|---|---|---|
| RPO (последняя запись пульса до аварии) | ≤ 300 с | **33 с** — 15 последних записей потеряны (несохранённый сегмент WAL; `archive_timeout` 60 с) |
| RTO (авария → PASS smoke) | ≤ 7200 с | **22 с** на стенде; на ВМ добавятся создание ВМ, bootstrap и загрузка образов — оценка 40–60 мин (`RESTORE.md`) |
| Целостность | 0 нарушений | 14 проверок, 0 |
| Сессия клиента после восстановления | действует | `/v1/vehicles` = 200 |

Первая версия учения останавливала стек штатно — PostgreSQL успевал архивировать последний сегмент и RPO
выходил 1 с; учение исправлено на SIGKILL. Ежемесячная проверка `backup.sh restore-check`
(изолированный контейнер, `archive_mode=off`, аудит) — PASS за 4 с.

## Тест алертов (2026-10-19, стенд)
Канал — приёмник стенда (webhook Alertmanager), затем — Telegram-бот владельца (ниже). Время — от сбоя до
приёма уведомления.

| Сбой | Алерт | Секунд | Итог |
|---|---|---|---|
| остановлен backend | ServiceDown (critical) | 160 | PASS |
| остановлен PostgreSQL под нагрузкой 2 запроса/с | HighErrorRate (critical) | 178 | PASS |
| (тот же сбой) | PostgresDown (critical) | 101 | PASS |
| остановлен notifications-worker | WorkerDown (critical) | 180 | PASS |
| недоступен production — видно с staging | PeerDown (critical) | 170 | PASS |
| (постоянно) | Watchdog → dead-man | 21 сигнал за время теста | PASS |

**Telegram (2026-10-19, 11:39, staging стенда, бот владельца, `chat_id` из переменных окружений GitHub):**
остановлен backend → BackendDown через 167 с, ServiceDown через 197 с (цель ≤ 300) — сообщения в чат
владельца; backend запущен → оба «восстановлено». Alertmanager: `alertmanager_notifications_total
{integration="telegram"}` 4, ошибок 0. Токен — файл стенда (`EV_STAND/telegram_token`, скрытый ввод
владельца), в GitHub — секрет `ALERT_TELEGRAM_BOT_TOKEN` обоих окружений.

Попутно алерты сработали и во время учения отката (простой сломанного выпуска) и первого неудачного
выпуска стенда — BackendDown, ServiceDown, WorkerStale.

## Ночной облегчённый прогон k6 (стенд)
`deploy/scripts/nightly-load.sh staging` (20 VU, 2 мин на стенде; на сервере — 5 мин): 9 310 запросов,
p95 21 мс, p99 59 мс, ошибок 0 % — пороги PASS; итоги в Prometheus (`k6_vus`, `k6_http_reqs_total`,
`k6_http_req_duration_p95/p99`, `k6_http_req_failed_rate`) — дашборд «нагрузка k6».

## ZAP через nginx (стенд)
`ZAP_TARGET=stand scripts/zap_server.sh` (ZAP 2.17.0 в сети «интернета» стенда, имена и TLS как у
клиента): активный скан API по `docs/openapi.yaml` от имени клиента и без токена, пассивный baseline обоих
кабинетов. **0 High, 0 Medium.** Low: COEP у кабинетов (принят в главе 25: `require-corp` блокировал бы
вложения S3); «Unexpected Content-Type» у API — HTML-ответ 404 самого nginx на путях вне `/v1` (в том числе
пробы облачных метаданных `/latest/meta-data/`) → исправлено (F11): API-хост отвечает JSON в формате
ошибок API, 502/503/504 — JSON `SERVICE_UNAVAILABLE`. Сводка — `docs/reviews/infra/zap-stand.md`. Повтор на
сервере — `security.yml`, job `zap-server` (BLOCKED до заказа ВМ).

## Найдено и исправлено стендом и учениями
| № | Находка | Исправление |
|---|---|---|
| F1 | `app.preflight` удалял каталог метрик — точку монтирования tmpfs (backend не стартовал) | очищается содержимое; тест |
| F2 | фиксированный адрес nginx (`FORWARDED_ALLOW_IPS`) занимал другой контейнер | динамические адреса — верхняя половина подсети (`ip_range`) |
| F3 | `{token}` в `map` nginx без кавычек; дубль `proxy_read_timeout` | исправлено; `nginx -t` обоих окружений — в `check-configs.sh` (CI) |
| F4 | PostgreSQL как PID 1 подбирал отсоединённый процесс асинхронной архивации pgBackRest и перезапускал все соединения посреди миграции | `init: true` (tini), `--init` в restore-check |
| F5 | новая БД рядом со старым репозиторием — `ArchiveMismatchError`, архивация WAL молча не идёт | `backup.sh init` делает `check` и сообщает о чужой stanza (бэкапы не удаляет); `RESTORE.md` |
| F6 | подмена каталога секретов ломала монтирование в работающем Alertmanager (dead-man не уходил) | секреты обновляются на месте (`rsync --delete`) |
| F7 | автооткат ждал тайм-аут health 180 с при падающем на старте контейнере (простой 3,5 мин) | второй перезапуск — сразу отказ |
| F8 | `RETURN`-trap bash срабатывал после выхода из функции (неопределённая переменная) | явная очистка и `EXIT` |
| F9 | тайм-ауты TLS Docker Hub на `compose pull` | `pull --policy missing` (образы по digest — локальный тот же) |
| F10 | лимиты N-06 (5 кодов в час на номер) мешали повторным учениям | кэш токена на стенде; лимиты работают как задумано |
| F11 | API-хост отдавал HTML-ответы nginx (404 вне `/v1`, 502 при падении backend) | JSON в формате ошибок API |

## Хвосты прошлых глав
| Хвост | Итог |
|---|---|
| Реальный staging вместо «проверенного образа»; `deploy-staging` — заглушка (ADR 0008 п. 6, 0013, 0021) | `deploy-staging` настоящий (`deploy-server.yml`); сервер — BLOCKED (не заказан) |
| nginx: статика, `/v1`, WebSocket, HSTS, CSP заголовком, `frame-ancestors`, `SECURITY_HEADERS`, TLS, `FORWARDED_ALLOW_IPS` (ADR 0025, 0029, 0013) | PASS (стенд): smoke каждой выкладки проверяет CSP и HSTS; тест `nginxHeaders.test.ts` сверяет список; XFF перезаписывается nginx |
| S3 и SMS в РБ/ЕАЭС (99-З п. 12, ADR 0017) | Timeweb (Россия, ЕАЭС) + A1 (Беларусь); Указ № 60 — риск (`OAC_3IN.md`) |
| IP сервера для A1, сценарий X5 (ADR 0027) | BLOCKED — сервер; письмо в A1 и шаги — `OWNER_ACTIONS_26.md` |
| `nosniff` на бакете (ADR 0017) | принятый S4 (ADR 0030 п. 10): Timeweb не задаёт заголовок объектам |
| Шифрование диска и бэкапов (ADR 0005) | бэкапы — AES-256 на клиенте; диски — нет (ADR 0030 п. 11) |
| Класс ИС и ТКЗИ (99-З п. 25); runbook НЦЗПД (п. 22) | класс 3-ин, требования приложения 3 — `OAC_3IN.md`; аттестация не проводится (решение владельца); `INCIDENT_PD.md` |
| Нагрузка на сервере, настройки PostgreSQL, Grafana для k6, ночные прогоны (ADR 0028) | настройки — `deploy/postgres/postgresql.conf`; k6 → Prometheus и ночной workflow — PASS (стенд); полный прогон на ВМ — BLOCKED, `LOAD_ON_SERVER.md` |
| Повтор ZAP на сервере (ADR 0029 п. 7) | `security.yml` → `zap-server`; на сервере — BLOCKED; через nginx стенда — см. ZAP выше |
| Процессы в развёртывании | API (2 процесса), `notifications-`, `analytics-`, `privacy-worker`, `migrate` (до переключения), nginx, certbot — `deploy/compose.yml` |

## Что осталось (до DONE)
Заказ ВМ и S3, DNS, секреты, бот алертов, dead-man, A1, Firebase production, Let's Encrypt — владелец
(`OWNER_ACTIONS_26.md`); затем агент: bootstrap ВМ, выкладка staging, повтор учений на сервере (откат,
DR на новую ВМ, алерты в Telegram с сервера), X5, ZAP по серверу, полный прогон ADR 0028 на production-ВМ,
release-PR `develop → main` (`v1.0.0-rc.2`) → cd-production (Approve владельца).
