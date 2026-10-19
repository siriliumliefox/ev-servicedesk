# Восстановление из бэкапа (DR)

ADR 0030 пп. 9, 22. **RPO ≤ 5 мин, RTO ≤ 2 ч.** pgBackRest: непрерывный архив WAL (`archive_timeout`
60 с), полный бэкап — вс 03:00, разностный — ежедневно 03:00 по Минску, PITR — 14 дней; repo1 — S3
окружения, repo2 (если задан) — SFTP внешней площадки. Шифрование AES-256 на клиенте — ключ
`PGBACKREST_CIPHER_PASS` (секрет окружения + копия владельца в менеджере паролей).

## Когда
- ВМ потеряна или диск повреждён — восстановление на **новую ВМ** (ниже);
- данные испорчены (ошибка релиза, удаление) — PITR на момент до события (`--time`), на новую ВМ или на
  эту после остановки и сохранения текущего тома;
- проверка — ежемесячно автоматически (`backup.sh restore-check`: изолированный контейнер без сети
  приложения, аудит целостности, счётчики) и учение на стенде (`scripts/infra_stack.sh drill-dr`).

## На новую ВМ (≈ 40–60 мин, основное — создание ВМ и загрузка образов)
1. Timeweb: новая ВМ той же конфигурации ([OWNER_ACTIONS_26.md](OWNER_ACTIONS_26.md) шаг 1), тот же
   регион; **освободившийся IPv4 перенести на новую ВМ** (адрес закреплён за аккаунтом — DNS и A1 не меняются).
2. `scp -r deploy root@<IP>:/root/` и `ssh root@<IP> /root/deploy/scripts/bootstrap.sh <env> ~/.ssh/ev-deploy-<env>.pub`
   (ключ хоста новый — обновить `SSH_KNOWN_HOSTS`: `ONLY=SSH_KNOWN_HOSTS scripts/set-infra-secrets.sh <env>`).
3. Выпуск без включения: cd-staging / cd-production ручным запуском или локально
   `deploy/scripts/make-bundle.sh <env> bundle.tar.gz` → `ssh deploy@<IP> receive-only <env> < bundle.tar.gz`.
4. Восстановление: `ssh root@<IP> sudo -u deploy /opt/ev/bin/restore.sh <env> <sha> [--time '2026-10-19 10:00:00+00'] [--repo 2]`
   — пустой том → `pgbackrest restore` → PostgreSQL догоняет WAL → `deploy.sh release` (миграции,
   smoke) → новый полный бэкап. В журнале — RTO.
5. Проверка: `docker exec ev-<env>-backend-1 python -m app.tools.integrity` — 0 нарушений; Grafana —
   алерты зелёные; вход клиента и сотрудника.
6. Сертификаты: `certs.sh letsencrypt <env>` (каталог certs/ на новой ВМ пуст).

## Чужая stanza
`backup.sh init` при выкладке: репозиторий содержит stanza **другого** кластера (новая пустая БД рядом со
старыми бэкапами) — архивация WAL не идёт, `ArchiveMismatchError`, алерты WalArchiveFailing / BackupMissing.
Скрипты бэкапы не удаляют. Решение владельца: восстановить старые данные (этот runbook) или сохранить
репозиторий (скопировать префикс `pgbackrest/` бакета) и очистить его, затем `backup.sh init`.

## Учение (стенд, 2026-10-19)
SIGKILL всех процессов → удаление контейнеров, томов и каталога окружения → «новая ВМ» → `restore.sh`:
RPO 33 с (последние 33 с записей потеряны — несохранённый сегмент WAL), RTO 22 с (стенд без создания ВМ
и загрузки образов), аудит — 0 нарушений, сессия клиента после восстановления действует. Подробно —
`docs/reviews/PRODUCTION_INFRA_26.md`.
