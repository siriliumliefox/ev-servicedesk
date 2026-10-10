# 0008. CI-гейт, защита веток, окружения и перенос staging-сервера

**Статус:** Принято, 2026-10-10 (владелец проекта, Issue #24)

## Контекст
Глава 4 требует git-flow с код-ревью, окружения local/dev/staging/production с разделением секретов,
CI на каждый PR, автодеплой на staging, проверку отката и изоляции секретов. Аудит (2026-10-10):
- CI — четыре workflow с path-фильтрами. Обязательная проверка в branch protection на таких workflow
  «висит» в ожидании на PR, который их не затронул, поэтому сделать их обязательными было нельзя;
- branch protection на `main`/`develop` не была включена, хотя `CONTRIBUTING.md` утверждал обратное;
- окружение `staging` — без политик и секретов, `dev` и `production` отсутствовали;
- откат через `workflow_dispatch` пересобирал образ из текущего HEAD, а не переиспользовал старый;
- staging-сервера нет, деплой — заглушка; аренда сервера ради главы 4 не оправдана — нагружать его нечем
  до появления сервисов (главы 10–17).

## Варианты
- **Обязательные проверки:** каждый workflow отдельно / один агрегирующий `ci-gate`.
- **Ревью:** обязательный approve (невозможен в одиночку) / без approve, но с обязательным CI.
- **Окружения:** local/dev/staging/production / local/staging/production.
- **Staging-сервер:** поднять сейчас / в главе 26 вместе с остальной инфраструктурой.

## Решение
1. **`ci.yml` — единая точка входа CI** на каждом PR (без path-фильтров) и push в `develop`/`main`.
   Job `changes` (`dorny/paths-filter`) решает, какие из переиспользуемых workflow (`backend-ci`, `web-ci`,
   `mobile-ci`, `docs-ci`) нужны; `secret-scan` (gitleaks) — всегда. Job `ci-gate` (`if: always()`)
   зелёный, только если `changes` и `secret-scan` успешны, а остальные — успешны или пропущены.
2. **Защита `main`/`develop`:** только PR; обязательная проверка `ci-gate` от GitHub Actions
   (`app_id` 15368), ветка PR актуальна; линейная история; без force-push и удаления;
   `enforce_admins: true`. Approve не требуется (`required_approving_review_count: 0`) — команда из одного
   человека; ограничение описано в `CONTRIBUTING.md`, при появлении ревьюера — `REVIEWS=1`.
3. **Окружения: local → staging (`develop`) → production (`main`).** `dev` убран: при одной ветке
   `develop` он дублировал бы staging. `production` — reviewer-владелец, обход админом выключен.
   Отклонение от формулировки MASTER_CHECKLIST («local/dev/staging/production», «изоляция dev/prod»)
   принято владельцем; изоляция проверяется для пары staging/production.
4. **Секреты:** разные `JWT_SECRET` в staging и production (`scripts/set-environment-secrets.sh`, значения
   не выводятся). Изоляцию проверяет `secrets-isolation.yml` по отпечаткам (16 hex SHA-256) в переменных
   репозитория `JWT_SECRET_FP_<ENV>`.
5. **Откат без пересборки:** `cd-staging.yml` с `git_sha` перетегирует `backend:staging-<sha>` →
   `backend:staging` (`docker buildx imagetools create`) и сверяет digest.
6. **Staging-сервер переносится в главу 26.** До неё `deploy-staging` — заглушка; реальны сборка,
   публикация образов в ghcr.io, перетегирование при откате и защита окружений.
7. `delete_branch_on_merge: true` — смерженные ветки удаляются автоматически.

## Последствия
- DoD главы 4 «все окружения подняты и доступны команде» выполнен на уровне GitHub Environments;
  доступность staging/production как серверов — DoD главы 26.
- Новый workflow-проверка подключается к `ci.yml` как переиспользуемый (`workflow_call`) и добавляется
  в `needs` у `ci-gate`; branch protection менять не нужно.
- Без зелёного `ci-gate` мерж невозможен ни для кого, включая владельца. Аварийный обход — только
  временным изменением защиты через `scripts/setup-branch-protection.sh`, осознанно и с записью в PR.
- `production`-проверка `secrets-isolation.yml` выполнима только из `main` — после первого релиза.
