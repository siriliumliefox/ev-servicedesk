# Окружения и секреты — EV-ServiceDesk

Глава 4, [ADR 0008](adr/0008-ci-gate-environments-staging-server.md); серверы — глава 26,
[ADR 0030](adr/0030-production-infrastructure.md). Модель: **local → staging → production**.
Секреты между окружениями не переиспользуются.

## Модель

| Окружение | Где живёт | Ветка деплоя | Секреты | Защита |
|---|---|---|---|---|
| **local** | машина разработчика | любая (не деплоится) | `.env` (gitignored), значения-заглушки из `.env.example` | — |
| **staging** | GitHub Environment `staging`; ВМ Timeweb Cloud, Москва (`deploy/`, ADR 0030; пока не заказана) | только `develop` (авто, `cd-staging.yml` → `deploy-server.yml`) | Environment Secrets, уникальные | деплой только из `develop`, обход админом выключен |
| **production** | GitHub Environment `production`; ВМ Timeweb Cloud, Санкт-Петербург (пока не заказана) | только `main` (`cd-production.yml`, merge-коммит release-PR) | Environment Secrets, уникальные | деплой только из `main` + **required reviewer** (владелец), обход админом выключен |

Окружения `dev` нет: при одном разработчике оно дублировало бы staging (та же ветка `develop`),
не давая отдельной проверки (ADR 0008).

Состояние (проверено API GitHub, 2026-10-10): `staging` — политика ветки `develop`, секрет `JWT_SECRET`;
`production` — политика ветки `main`, reviewer `siriliumliefox`, секрет `JWT_SECRET`.

## Почему GitHub Environments, а не Vault/AWS Secrets Manager

Облачной инфраструктуры пока нет (Глава 26). GitHub Environments бесплатны вместе с репозиторием и
покрывают нужное сейчас: разделённые секреты, ограничение по ветке, reviewer перед production. Когда
появится инфраструктура, хранение секретов может переехать в облачный secrets manager — модель
разделения не изменится.

## Reviewer на production при команде из одного человека

PR-ревью GitHub не позволяет одобрить собственный PR — поэтому обязательного approve в branch protection
нет (см. `CONTRIBUTING.md`). Environment protection — другой механизм: одобрить собственный деплой можно
(`prevent_self_review: false`), поэтому владелец назначен reviewer'ом `production`. Перед каждым
прод-деплоем нужно явно нажать «Approve» в GitHub Actions.

## Переменные окружения

Полный список — `.env.example`. Кратко:

| Переменная | Отличается по окружениям? | Источник значения |
|---|---|---|
| `DATABASE_URL` | Да | PostgreSQL окружения на его ВМ; собирает `deploy/scripts/render-secrets.sh` из `POSTGRES_PASSWORD` |
| `REDIS_URL` | Да | Redis окружения на его ВМ (`deploy/compose.yml`) |
| `JWT_SECRET` | Да | `scripts/set-environment-secrets.sh` (задан для staging и production) |
| `SMS_PROVIDER_API_KEY` | Да (когда провайдер выбран) | пока пусто — бизнес-решение |
| `S3_*` | Да | бакеты окружения в S3 Timeweb (`<окружение>-media`, `<окружение>-backup`; ADR 0030 п. 10); local — MinIO из `docker compose`. Вне local/test backend не стартует без ключей или без доступного бакета (ADR 0017) |
| `PUSH_PROVIDER`, `FCM_SERVICE_ACCOUNT_JSON` | Да | ADR 0019: staging — `fake`, пока нет Firebase-проекта; production — только `fcm`. JSON-ключ сервисного аккаунта вводит владелец (`scripts/set-fcm-secret.sh`), один Firebase-проект с разными app id. Worker уведомлений — тот же образ, команда `python -m app.workers.notifications` |
| `ANALYTICS_REFRESH_SECONDS` | Нет | ADR 0020: интервал обновления витрины дашборда (по умолчанию 300 с). Worker аналитики — тот же образ, команда `python -m app.workers.analytics` (`--once` — одно обновление) |

## Настройка (идемпотентно, нужен `gh auth login` с правами admin)

```bash
./scripts/setup-branch-protection.sh     # main/develop: PR, ci-gate, линейная история, на админа тоже
./scripts/setup-github-environments.sh   # staging ← develop; production ← main + reviewer; удаляет dev
./scripts/set-environment-secrets.sh     # генерирует и записывает JWT_SECRET; повторный запуск = ротация
```

`set-environment-secrets.sh` не печатает значения: `openssl rand` → stdin `gh secret set`. В переменные
репозитория пишется только отпечаток `JWT_SECRET_FP_<ENV>` (первые 16 hex SHA-256) для проверки изоляции.

### Проверка изоляции секретов

Workflow `secrets-isolation.yml` (ручной запуск):
- из `develop`: job без окружения не видит `JWT_SECRET`; политики веток и reviewer заданы; отпечатки
  окружений различаются; job в `staging` видит секрет со своим отпечатком и не видит секрет `production`;
- из `main` (после одобрения): то же для `production`.

```bash
gh workflow run secrets-isolation.yml --ref develop
```

## CD на staging

`cd-staging.yml` при push в `develop` (изменения в `backend/`, `web-*/`):
1. Собирает backend-образ и публикует в `ghcr.io/<repo>/backend` с тегами `staging-<sha>` и `staging`.
2. Собирает статику `web-engineer`/`web-admin` (build-артефакты, хранятся 14 дней).
3. Выкладывает на ВМ staging (`deploy-server.yml`: bundle по SSH → `deploy.sh`: миграции, up, smoke, автооткат).
   Пока ВМ не заказана (переменная окружения `SSH_HOST` пуста) — «сервер не настроен» (ADR 0030 п. 2).

### Откат без пересборки

```bash
./scripts/rollback-staging.sh <sha>
```

Запускает `cd-staging.yml` из `develop` с `git_sha`: сборка пропускается, существующий
`backend:staging-<sha>` перетегируется в `backend:staging` (`docker buildx imagetools create`), затем digest
сверяется — в логе `PASS`/`FAIL`. Откатиться можно на коммит, который уже собирался `cd-staging.yml`.
Кроме перетегирования, `deploy-staging` выполняет на ВМ `ssh deploy@<ВМ> rollback staging <sha>` — выпуск
из последних пяти на ВМ (`docs/runbooks/ROLLBACK.md`).

## Серверы (глава 26, ADR 0030)

Переменные окружения GitHub (не секреты): `SSH_HOST` (IPv4 ВМ; пусто — выкладка пропускается),
`S3_MEDIA_BUCKET`, `S3_BACKUP_BUCKET`, `TELEGRAM_CHAT_ID`, `SMS_PROVIDER` (staging: `fake` до разрешения IP в
A1). Переменные репозитория: `STAGING_MEDIA_ORIGIN`, `PRODUCTION_MEDIA_ORIGIN` — origin S3 для CSP кабинетов.

| Секрет окружения | Откуда |
|---|---|
| `SSH_DEPLOY_KEY`, `SSH_KNOWN_HOSTS` | `scripts/set-infra-secrets.sh` (ключ генерируется, отпечаток хоста сверяет владелец) |
| `POSTGRES_PASSWORD`, `POSTGRES_MONITOR_PASSWORD` | генерирует `scripts/set-infra-secrets.sh` |
| `PGBACKREST_CIPHER_PASS` | генерирует `scripts/set-infra-secrets.sh`, **копия — у владельца офлайн** |
| `S3_ACCESS_KEY`, `S3_SECRET_KEY`, `BACKUP_S3_ACCESS_KEY`, `BACKUP_S3_SECRET_KEY` | панель Timeweb → `scripts/set-infra-secrets.sh` |
| `GRAFANA_ADMIN_PASSWORD` | владелец (`scripts/set-infra-secrets.sh`) |
| `ALERT_TELEGRAM_BOT_TOKEN`, `DEADMAN_URL` | владелец: бот @BotFather, healthchecks.io |
| `SMS_PROVIDER_USER`, `SMS_PROVIDER_API_KEY`, `SMS_SENDER` | `scripts/set-a1-secrets.sh` |
| `FCM_SERVICE_ACCOUNT_JSON` (production) | `scripts/set-fcm-secret.sh` |
| `SMS_TEST_PHONES`, `SMS_TEST_CODE` (staging) | тестовые номера сквозных проверок и ночного прогона |
| `PGBACKREST_REPO2_SFTP_HOST` (необязательно) | внешняя площадка repo2 |

На ВМ секреты — `/opt/ev/<окружение>/secrets/*.env` (0600, пользователь `deploy`), обновляются каждой
выкладкой из bundle. Шаги владельца — `docs/runbooks/OWNER_ACTIONS_26.md`.
