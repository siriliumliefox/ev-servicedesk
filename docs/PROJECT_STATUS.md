# PROJECT_STATUS — подтверждённое состояние

Обновлено: 2026-10-08. Статус меняется только по фактам (код, тесты, CI, PR).

Статусы: `NOT_STARTED`, `IN_PROGRESS`, `VERIFYING` (артефакты есть, DoD не сверен), `PARTIAL`, `BLOCKED`, `DONE`.

| Глава | Название | Статус | Доказательства / примечание |
|---|---|---|---|
| 00 | Перенос и настройка рабочей среды | DONE | PR #3, merge commit `a3fb606` в `develop` |
| 01 | Финализация требований и глоссария | DONE | PR #5, `docs/requirements/`, ADR 0002, тег `requirements-baseline-v1` |
| 02 | ER-схема БД | DONE | PR #12, merge `05149dd` в `develop`, CI зелёный; ORM + Alembic (0001–0003), тесты `backend/tests/db/`, ADR 0003–0005, `docs/DB_SCHEMA.md`; follow-up #13 |
| 03 | API-контракты OpenAPI | VERIFYING | `docs/openapi.yaml`, Swagger UI; mock-сервер не подтверждён |
| 04 | Репозиторий, окружения, CI/CD | VERIFYING | 4 workflow, `docs/ENVIRONMENTS.md`; локально всё зелёное 2026-10-08 |
| 05 | Алгоритм «светофор» и регламенты ТО | NOT_STARTED | Claude заявлял готовность — в репозитории нет кода и тестов |
| 06–28 | см. `MASTER_CHECKLIST.md` | NOT_STARTED | — |

## Локальная проверка среды (2026-10-08, `~/Developer/ev-servicedesk`)
| Проверка | Результат |
|---|---|
| `ruff check` | PASS |
| `pytest` | PASS (1 тест) |
| `npm ci` | PASS |
| `flutter analyze` / `flutter test` | PASS / PASS (1 тест) |
| `docker compose up` | PASS, postgres и redis healthy |

## Известные расхождения
- Claude memory: «главы 1–5 завершены», `.clinerules`, `docs/PROJECT_HANDOFF.md` — в репозитории отсутствуют.
