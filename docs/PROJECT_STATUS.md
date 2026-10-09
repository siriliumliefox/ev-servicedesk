# PROJECT_STATUS — подтверждённое состояние

Обновлено: 2026-10-10. Статус меняется только по фактам (код, тесты, CI, PR).

Статусы: `NOT_STARTED`, `IN_PROGRESS`, `VERIFYING` (артефакты есть, DoD не сверен), `PARTIAL`, `BLOCKED`, `DONE`.

| Глава | Название | Статус | Доказательства / примечание |
|---|---|---|---|
| 00 | Перенос и настройка рабочей среды | DONE | PR #3, merge commit `a3fb606` в `develop` |
| 01 | Финализация требований и глоссария | DONE | PR #5, `docs/requirements/`, ADR 0002, теги `requirements-baseline-v1`, `requirements-baseline-v1.1` (RBAC-02, PR #16) |
| 02 | ER-схема БД | DONE | PR #12, merge `05149dd` в `develop`, CI зелёный; ORM + Alembic (0001–0004), тесты `backend/tests/db/`, ADR 0003–0006, `docs/DB_SCHEMA.md`; follow-up #13 (PR #14); техдолг #15 — закрыт: PR #16 (`9f3e6ab`), PR #19 (`7a52fd3`, `docs/compliance/PD_99Z_CHECKLIST.md`), CI зелёный; открытые пункты 99-З — в главах 10, 13, 15, 25–28 |
| 03 | API-контракты OpenAPI | VERIFYING | `docs/openapi.yaml` 1.0.0-rc3 (валиден, docs-ci), Swagger UI; mock-сервер не подтверждён |
| 04 | Репозиторий, окружения, CI/CD | VERIFYING | 4 workflow, `docs/ENVIRONMENTS.md`; локально всё зелёное 2026-10-08 |
| 05 | Алгоритм «светофор» и регламенты ТО | NOT_STARTED | Claude заявлял готовность — в репозитории нет кода и тестов |
| 06–28 | см. `MASTER_CHECKLIST.md` | NOT_STARTED | — |

## Локальная проверка (2026-10-10, `~/Developer/ev-servicedesk`, PR #16)
| Проверка | Результат |
|---|---|
| `ruff check` / `ruff format --check` | PASS |
| `REQUIRE_DB=1 pytest -q` (PostgreSQL 16) | PASS (65 тестов; в CI backend-ci — 65 passed) |
| `alembic upgrade head`, upgrade → downgrade base → upgrade | PASS (`0004`) |
| DDL/ERD `--check`, `openapi-spec-validator`, Swagger sync | PASS |
| `npm ci` / lint / build | PASS |
| `flutter analyze` / `flutter test` | PASS / PASS (1 тест) |
| `docker compose up`, `docker build backend` (Poetry 2.5.1) | PASS |
| gitleaks pre-commit hook (`.githooks/`) | PASS |

## Известные расхождения
- Claude memory: «главы 1–5 завершены», `.clinerules`, `docs/PROJECT_HANDOFF.md` — в репозитории отсутствуют.
