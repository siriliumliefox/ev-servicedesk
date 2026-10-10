# PROJECT_STATUS — подтверждённое состояние

Обновлено: 2026-10-10. Статус меняется только по фактам (код, тесты, CI, PR).

Статусы: `NOT_STARTED`, `IN_PROGRESS`, `VERIFYING` (артефакты есть, DoD не сверен), `PARTIAL`, `BLOCKED`, `DONE`.

| Глава | Название | Статус | Доказательства / примечание |
|---|---|---|---|
| 00 | Перенос и настройка рабочей среды | DONE | PR #3, merge commit `a3fb606` в `develop` |
| 01 | Финализация требований и глоссария | DONE | PR #5, `docs/requirements/`, ADR 0002, теги `requirements-baseline-v1`, `requirements-baseline-v1.1` (RBAC-02, PR #16), `requirements-baseline-v1.2` (RBAC-03, PR #21) |
| 02 | ER-схема БД | DONE | PR #12, merge `05149dd` в `develop`, CI зелёный; ORM + Alembic (0001–0004), тесты `backend/tests/db/`, ADR 0003–0006, `docs/DB_SCHEMA.md`; follow-up #13 (PR #14); техдолг #15 — закрыт: PR #16 (`9f3e6ab`), PR #19 (`7a52fd3`, `docs/compliance/PD_99Z_CHECKLIST.md`), CI зелёный; открытые пункты 99-З — в главах 10, 13, 15, 25–28 |
| 03 | API-контракты OpenAPI | DONE | Issue #18, PR #21 (`973ab19` в `develop`), CI зелёный (backend-ci 361 passed, docs-ci, web-ci); `docs/openapi.yaml` 1.0.0 заморожен, тег `api-contract-v1`, ADR 0007; пагинация всех коллекций, `/me`, `/users`, `/analytics/*`; Spectral, `backend/tests/contract`, Prism mock (`npm run mock`, smoke в CI), клиент `web-shared`, `oasdiff` против базовой ветки |
| 04 | Репозиторий, окружения, CI/CD | DONE | Issue #24, PR #25 (`0573f1b`), PR #28 (`bcbc3c9`), ADR 0008. `ci-gate` — единственная обязательная проверка: PR с одним `.gitignore` (#26) — зелёный, проверки сервисов skipped; PR со сломанным тестом (#27) — красный, merge заблокирован; PR #25 — зелёные backend, web ×2, mobile, docs, secret-scan. Защита `main`/`develop` (`enforce_admins`): прямой push в `develop` отклонён. Откат без пересборки (run 38030052595): digest `backend:staging` = `staging-9f3e6ab` — PASS, затем возврат на `973ab19` — PASS. `secrets-isolation` из `develop` (run 38030187956): 9 × PASS; production-проверка — из `main` после первого релиза. Окружения `staging` (← `develop`), `production` (← `main`, reviewer); `dev` убран; staging/production-серверы — глава 26 (ADR 0008) |
| 05 | Алгоритм «светофор» и регламенты ТО | NOT_STARTED | Claude заявлял готовность — в репозитории нет кода и тестов |
| 06–28 | см. `MASTER_CHECKLIST.md` | NOT_STARTED | — |

## Локальная проверка (2026-10-10, `~/Developer/ev-servicedesk`, PR #16, #21)
| Проверка | Результат |
|---|---|
| `ruff check` / `ruff format --check` | PASS |
| `REQUIRE_DB=1 pytest -q` (PostgreSQL 16) | PASS (361 тест: 65 БД + 296 контракт; в CI backend-ci — 361 passed) |
| `alembic upgrade head`, upgrade → downgrade base → upgrade | PASS (`0004`) |
| DDL/ERD `--check`, `openapi-spec-validator`, Swagger sync | PASS |
| `npm run lint:api` (Spectral) / `npm run test:mock` (Prism, 7 проверок) / `scripts/check_api_breaking.sh` | PASS / PASS / PASS |
| `npm ci` / lint / build | PASS |
| `flutter analyze` / `flutter test` | PASS / PASS (1 тест) |
| `docker compose up`, `docker build backend` (Poetry 2.5.1) | PASS |
| gitleaks pre-commit hook (`.githooks/`) | PASS |

## Известные расхождения
- Claude memory: «главы 1–5 завершены», `.clinerules`, `docs/PROJECT_HANDOFF.md` — в репозитории отсутствуют.
