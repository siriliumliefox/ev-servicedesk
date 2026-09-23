# Окружения и секреты — EV-ServiceDesk

Глава 4, шаг 3. Четыре уровня, каждый — свои секреты, ничего не переиспользуется между ними.

## Модель

| Окружение | Где живёт | Ветка деплоя | Секреты | Защита |
|---|---|---|---|---|
| **local** | MacBook Pro M5 Pro разработчика | любая (не деплоится) | `.env` (gitignored), local-safe заглушки из `.env.example` | нет — это ваша машина |
| **dev** | GitHub Environment `dev` | `develop` (авто) | GitHub Environment Secrets, уникальные | нет — быстрая итерация |
| **staging** | GitHub Environment `staging` | `develop` (авто, Глава 4 шаг 5) | GitHub Environment Secrets, уникальные | ветка ограничена `develop` |
| **production** | GitHub Environment `production` | `main` (вручную/по тегу релиза) | GitHub Environment Secrets, уникальные | ветка ограничена `main` + **required reviewer** перед деплоем |

## Почему GitHub Environments, а не Vault/AWS Secrets Manager

На этом этапе (Глава 4) реальной облачной инфраструктуры ещё нет — она
появится в Главе 26. GitHub Environments — единственное, что уже доступно
бесплатно вместе с репозиторием, и покрывает ровно то, что нужно сейчас:
разделённые секреты + ограничение по ветке + reviewer-гейт на прод. Когда
Глава 26 поднимет реальную инфраструктуру, физическое хранение секретов
может переехать в облачный secrets manager — но модель разделения
(dev/staging/production никогда не шарят значения) не изменится.

## Важное отличие от код-ревью (Глава 4, шаг 2)

PR-ревью на GitHub не даёт approve собственного PR — отсюда компромисс с
`required_approving_review_count: 0` в `CONTRIBUTING.md`. Environment
protection rules — **другой механизм**, self-approve там разрешён. Поэтому
`scripts/setup-github-environments.sh` назначает вас же required reviewer
на `production`: перед каждым прод-деплоем придётся явно нажать «Approve»
в интерфейсе GitHub Actions — настоящая пауза для проверки, а не фикция,
даже при команде из одного человека.

## Переменные окружения

Полный список и комментарии — `.env.example` в корне репозитория. Кратко:

| Переменная | Отличается по окружениям? | Источник значения |
|---|---|---|
| `DATABASE_URL` | Да, всегда | своя БД на каждое окружение (даже если физически один сервер — разные `POSTGRES_DB`) |
| `REDIS_URL` | Да, всегда | аналогично |
| `JWT_SECRET` | Да, всегда | `scripts/generate-secret.sh`, никогда не переиспользовать |
| `SMS_PROVIDER_API_KEY` | Да (когда провайдер выбран) | пока пусто — отдельное бизнес-решение, не техническое |
| `S3_*` | Да | свой bucket/credentials на окружение |
| `FCM_SERVICE_ACCOUNT_JSON` | Обычно один Firebase-проект с разными app id на dev/prod — уточнить в Главе 15 |

## Первоначальная настройка (когда репозиторий появится на GitHub)

```bash
# 1. Ветки и защита (Глава 4, шаг 2 — если ещё не сделано)
export GITHUB_TOKEN=...
export GITHUB_REPO=owner/ev-servicedesk
./scripts/setup-branch-protection.sh

# 2. Окружения + reviewer на прод
export PROD_APPROVER=<ваш GitHub-логин>
./scripts/setup-github-environments.sh

# 3. Секреты — по одному на переменную, значения РАЗНЫЕ на каждое окружение
for env in dev staging production; do
  gh secret set JWT_SECRET --env "$env"        # вставит вывод generate-secret.sh
  gh secret set DATABASE_URL --env "$env"
  gh secret set REDIS_URL --env "$env"
done
```

## CD на staging (Глава 4, шаг 5)

`workflows/cd-staging.yml` запускается при мерже в `develop`:
1. Собирает и публикует backend-образ в `ghcr.io` (тег — и `staging`, и `staging-<sha>` для отката) — **реально рабочий шаг**.
2. Собирает статику `web-engineer`/`web-admin`, кладёт как build-артефакт — **реально рабочий шаг**.
3. «Выкатывает» на staging-сервер — **заглушка**: сервера ещё нет (Глава 26). Когда появится, поменяется только этот job, первые два трогать не придётся.

### Откат
`scripts/rollback-staging.sh <git-sha>` — перезапускает деплой уже
собранного образа по SHA, ничего не пересобирая. Быстрее отката через git
revert + новый деплой. Реально сработает только после Главы 26 (нужен
настоящий шаг деплоя, не заглушка) — сам механизм (`workflow_dispatch` +
переиспользование готового образа по тегу) уже готов и не потребует правок.


Ни один из скриптов в этой сессии не выполнялся против настоящего GitHub —
нет ни репозитория, ни токена в этой песочнице. Синтаксис обоих скриптов
проверен (`bash -n`), логика — на API-документации GitHub Environments.
**Реальная проверка изоляции секретов dev/prod возможна только после того,
как вы прогоните эти скрипты на своём репозитории** — это тот пункт DoD,
который я не могу закрыть за вас, только подготовить.
