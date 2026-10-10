# Окружения и секреты — EV-ServiceDesk

Глава 4, [ADR 0008](adr/0008-ci-gate-environments-staging-server.md). Модель: **local → staging → production**.
Секреты между окружениями не переиспользуются.

## Модель

| Окружение | Где живёт | Ветка деплоя | Секреты | Защита |
|---|---|---|---|---|
| **local** | машина разработчика | любая (не деплоится) | `.env` (gitignored), значения-заглушки из `.env.example` | — |
| **staging** | GitHub Environment `staging`; сервер — Глава 26 | только `develop` (авто, `cd-staging.yml`) | Environment Secrets, уникальные | деплой только из `develop`, обход админом выключен |
| **production** | GitHub Environment `production`; сервер — Глава 26 | только `main` | Environment Secrets, уникальные | деплой только из `main` + **required reviewer** (владелец), обход админом выключен |

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
| `DATABASE_URL` | Да | своя БД на окружение — Глава 26 |
| `REDIS_URL` | Да | аналогично — Глава 26 |
| `JWT_SECRET` | Да | `scripts/set-environment-secrets.sh` (задан для staging и production) |
| `SMS_PROVIDER_API_KEY` | Да (когда провайдер выбран) | пока пусто — бизнес-решение |
| `S3_*` | Да | свой bucket/credentials на окружение — Глава 26 |
| `FCM_SERVICE_ACCOUNT_JSON` | уточнить в Главе 15 | обычно один Firebase-проект с разными app id |

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
3. «Выкатывает» на staging — **заглушка** до Главы 26: сервера нет (ADR 0008). Меняется только этот job.

### Откат без пересборки

```bash
./scripts/rollback-staging.sh <sha>
```

Запускает `cd-staging.yml` из `develop` с `git_sha`: сборка пропускается, существующий
`backend:staging-<sha>` перетегируется в `backend:staging` (`docker buildx imagetools create`), затем digest
сверяется — в логе `PASS`/`FAIL`. Откатиться можно на коммит, который уже собирался `cd-staging.yml`.
Пока сервера нет, «откат» меняет то, на что указывает тег `staging`; после Главы 26 сервер будет
подтягивать именно этот тег.
