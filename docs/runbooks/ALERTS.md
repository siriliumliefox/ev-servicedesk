# Алерты — что делать

ADR 0030 п. 14; правила — `deploy/prometheus/rules/ev.yml` (тесты — `deploy/prometheus/tests/ev_test.yml`),
по журналу — `deploy/loki/rules/fake/ev.yml`. **Critical** приходит в Telegram круглосуточно и повторяется
раз в час, **warning** — 08:00–22:00 по Минску. В сообщении — окружение, сервис, значение; ПД нет.

Доступ к ВМ — ключ администратора: `ssh -i ~/.ssh/ev_admin root@<IP>`. Grafana, Prometheus, Alertmanager —
только через туннель: `ssh -i ~/.ssh/ev_admin -L 3000:127.0.0.1:3000 -L 9090:127.0.0.1:9090 -L 9093:127.0.0.1:9093 root@<IP>`,
затем http://127.0.0.1:3000 (дашборд «EV-ServiceDesk — обзор»). Команды compose на ВМ:
`cd /opt/ev/<env>/current/deploy && docker compose -p ev-<env> ps` (полный набор файлов и env —
`deploy/scripts/lib.sh`, функция `dc`; проще — `deploy.sh status <env>` и `docker ps`).

## ServiceDown
`/health` недоступен снаружи через nginx и TLS 2 мин (critical). Сначала — что упало:
1. `docker ps --filter label=com.docker.compose.project=ev-<env>` — backend `unhealthy`/`restarting`, nginx нет?
2. `docker logs --tail 100 ev-<env>-backend-1` — ошибка старта (`app.preflight`: настройки, бакет S3).
3. Только что был релиз — `deploy.sh status <env>`; откат — [ROLLBACK.md](ROLLBACK.md).
4. ВМ недоступна целиком — консоль Timeweb; одновременно должен прийти PeerDown с соседней ВМ и
   письмо dead-man.

## PeerDown
Соседняя ВМ не отвечает снаружи (production с staging — critical; staging с production — warning через
5 мин). Если своего ServiceDown у соседа нет — сеть между городами или DNS: `dig +short api.etsautogomel.by`,
`curl -v https://api.etsautogomel.by/health` с обеих ВМ.

## PostgresDown
Экспортёр не видит PostgreSQL 1 мин. `docker logs --tail 100 ev-<env>-postgres-1`; диск (DiskAlmostFull);
перезапуск — `docker compose … up -d postgres`. Данные потеряны или повреждены — [RESTORE.md](RESTORE.md).

## RedisDown
Redis недоступен: вход (коды, лимиты), WebSocket и отзыв сессий не работают — API отвечает 503 (fail
closed). `docker logs ev-<env>-redis-1`, `up -d redis`. Данные Redis восстанавливать не нужно (TTL, AOF).

## TargetDown
Экспортёр или сервис мониторинга не отдаёт метрики 10 мин — алерты по нему слепы. `docker ps`, `up -d <сервис>`.

## HighErrorRate
Доля 5xx > 5 % за 5 мин (critical; > 1 % за 15 мин — ErrorRateElevated, warning). Grafana → «Доля 5xx» и
«p95 по маршрутам» — какие маршруты; Loki: `{env="<env>", level="ERROR"}`. Частые причины: БД или Redis
(их алерты придут тоже), релиз (откат), S3 (вложения), A1 (SMS — `SMS_UNAVAILABLE` 503 — это не 5xx
сервера, а отказ провайдера; проверить кабинет A1 и разрешённый IP).

## SlowReads
p95 чтения > 300 мс 10 мин (норматив ADR 0028). Grafana: какие маршруты; PostgreSQL — `pg_stat_statements`
(топ запросов), CPU и память ВМ. Регресс после релиза — сравнить с прошлой неделей на дашборде.

## WorkerStale
Worker без успешного цикла дольше трёх интервалов (уведомления — 10 мин, аналитика — 20 мин, ПД — 3,5 ч)
или не отвечает (WorkerDown). `docker logs --tail 100 ev-<env>-<worker>-1` — исключение цикла; БД или
Redis. Уведомления стоят — push не уходят; ПД — срок анонимизации идёт (AnonymizationOverdue).

## PushQueueBacklog
Готовая доставка push ждёт > 10 мин: FCM отвечает медленно или ошибками, worker перегружен. Журнал
`app.workers.notifications`, ответы FCM; рассылка 10 000 получателям — до 5 мин (ADR 0028).

## AnonymizationOverdue
Клиент ждёт анонимизации больше 14 дней — до срока 99-З (15 дней) сутки. Журнал `app.workers.privacy`
(ERROR «больше 14 дней»), S3 (удаление вложений), SMS «данные удалены». Если до срока не успеть —
`docs/runbooks/INCIDENT_PD.md` (оценка нарушения).

## IntegrityViolations
Ежесуточный аудит `app.tools.integrity` нашёл нарушения. На ВМ: `docker exec ev-<env>-backend-1 python -m app.tools.integrity`
— список проверок и id. Не исправлять вручную без разбора: дефект кода — Issue S1/S2.

## BackupStale
Бэкап старше 26 ч / полный старше 8 суток / нет ни одного / WAL не архивируется 15 мин (RPO ≤ 5 мин нарушен)
/ ошибки архивации. `deploy/scripts/backup.sh info <env>` (через ev-ssh: `ssh deploy@<IP> backup <env> info`),
`systemctl status ev-backup@diff`, журнал `/var/log/pgbackrest` в контейнере PostgreSQL. Частые причины:
ключи S3, место в бакете, сеть; «другой кластер» в репозитории — [RESTORE.md](RESTORE.md#чужая-stanza).
Ручной запуск: `ssh deploy@<IP> backup <env> full`.

## Disk
Диск > 85 % (warning) или > 95 % (critical). `df -h`, `docker system df`; старые образы —
`docker image prune -a --filter until=168h`; журналы Docker ограничены (50 МБ × 5 на контейнер); Loki и
Prometheus — сроки хранения (ADR 0030 п. 15). PostgreSQL и WAL — `pg_database_size`, спул pgBackRest.

## Memory
Память ВМ > 90 % 10 мин. `docker stats --no-stream`: лимиты контейнеров в compose (backend 2 ГБ,
PostgreSQL 2 ГБ). Рост без нагрузки — утечка (наблюдение ADR 0028: +9 %/ч в soak) — перезапуск сервиса и Issue.

## ContainerRestarting
Контейнер перезапускался больше 2 раз за 15 мин: `docker logs` и `docker inspect -f '{{.State.ExitCode}}'`.

## Certificate
Сертификат истекает через < 14 дней — certbot не продлил. `docker logs ev-<env>-certbot-1`; HTTP-01 требует
доступный порт 80 и DNS на эту ВМ. Ручное продление — `docker compose … run --rm certbot renew`.
Запасного бесплатного УЦ для `.by` нет (ADR 0030 п. 18).

## StaffPasswordBruteforce
Потолок неудачных входов на номер сотрудника (подбор пароля с разных адресов, ADR 0029 п. 11) или всплеск
неудачных входов. Loki: `{logger="app.security"} | json | outcome!="success"` — IP и время. Номер
временно заблокирован лимитом; при необходимости — сброс пароля сотрудника администратором (отзывает
сессии). Признаки утечки — `docs/runbooks/INCIDENT_PD.md`.

## Watchdog (dead-man)
Не алерт для человека: Alertmanager шлёт его healthchecks.io раз в минуту. Если сигнал пропал на 10 мин,
healthchecks.io пишет владельцу — не работает сама цепочка алертов (ВМ, Prometheus, Alertmanager или сеть).
