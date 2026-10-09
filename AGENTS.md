# AGENTS.md — правила работы AI-агентов с EV-ServiceDesk

Обязательно для любого AI-агента (Perplexity Computer, Claude, Codex и др.).

## Источники истины (по убыванию приоритета)
1. Код и реально запущенные тесты.
2. Git: status, diff, log, ветки, `origin/develop`.
3. GitHub Issues, PR, CI.
4. `docs/openapi.yaml`, `docs/EV_ServiceDesk_Glava2_DDL.sql`, ORM, Alembic, `docs/adr/`.
5. `docs/TZ.md`, `docs/MASTER_CHECKLIST.md` (28 глав).
6. `docs/PROJECT_STATUS.md`, `docs/ROADMAP.md`.
7. История Claude. Заявления прошлых AI без кода/теста/commit не считаются выполненной работой.

## Структура
| Путь | Назначение |
|---|---|
| `backend/` | FastAPI, Python 3.12, Poetry, SQLAlchemy 2, Alembic |
| `web-engineer/`, `web-admin/`, `web-shared/` | React + TS + Vite + Tailwind (npm workspaces) |
| `mobile/` | Flutter, iOS + macOS |
| `docs/` | ТЗ, чек-лист, контракты, статус, ADR |
| `.github/workflows/` | CI/CD |

## Команды
```bash
# setup
npm ci
(cd backend && poetry install)
(cd mobile && flutter pub get)
docker compose up -d          # postgres:16, redis:7
git config core.hooksPath .githooks   # pre-commit: gitleaks

# проверки
(cd backend && poetry run ruff check . && poetry run pytest -q)
npm run lint --workspaces --if-present
npm run build --workspaces --if-present
(cd mobile && flutter analyze && flutter test)
docker compose config -q
npm run lint:api && npm run test:mock   # контракт: Spectral + mock (Prism)
scripts/check_api_breaking.sh           # ломающие изменения OpenAPI против origin/develop (Docker)

# БД (Глава 2): схема только через Alembic; тесты схемы — на БД *_test (TEST_DATABASE_URL)
(cd backend && poetry run alembic upgrade head)
(cd backend && poetry run python scripts/export_ddl.py && poetry run python scripts/export_erd.py)
```

## Процесс главы
- Одна глава = один Computer-чат `Глава NN — Название` = одна ветка = один PR в `develop`.
- Ветки: `feature/<issue>-<slug>`, `fix/<issue>-<slug>`, `chore/<slug>`, `hotfix/<issue>-<slug>`.
- Начало: прочитать главу в `MASTER_CHECKLIST.md`, `PROJECT_STATUS.md`, ADR; проверить Git; показать план и DoD.
- Итерации: изменение → тест → проверки → diff → дальше.
- `DONE` только при выполненном оригинальном DoD, зелёном CI и смерженном PR. Иначе `PARTIAL`/`BLOCKED`.
- Статусы проверок: `PASS`, `FAIL`, `NOT RUN`, `BLOCKED`.

## Архитектура
- Модульный монолит; доменная логика вне HTTP routes и UI.
- Схема БД только через Alembic (upgrade + downgrade).
- OpenAPI, DDL, ORM, Pydantic синхронны; изменение контракта = OpenAPI + тесты + клиенты. После изменения `docs/openapi.yaml`: `npm run gen:api`, Swagger sync, `backend/tests/contract` (ADR 0007).
- RBAC `client`/`engineer`/`admin` + object-level authorization.

## Безопасность
- Не читать и не выводить `.env`; в документации только имена переменных (см. `.env.example`).
- Не коммитить секреты, персональные данные, экспорт Claude (`light_metadata` особенно).
- Перед commit: `git diff --cached` + поиск секретов. Pre-commit hook `.githooks/pre-commit` запускает
  `gitleaks git --pre-commit --staged`; без gitleaks коммит блокируется. Подключение (один раз на клон):
  `brew install gitleaks && git config core.hooksPath .githooks`. В CI — `docs-ci` (gitleaks-action).
  `--no-verify` не использовать.

## Известные ловушки
- Poetry 2.5.1 (как в CI, Dockerfile и `poetry.lock`); окружение — Python 3.12 (`poetry env use python3.12`).
- После переноса папки пересоздавать `backend/.venv`, `mobile/.dart_tool`, Flutter `ephemeral`.
- Adminer: сервер `postgres`, не `db`.
- Не класть `node_modules` и `.git` в архивы; не создавать `.git` в домашнем каталоге.
- Песочница Computer не имеет доступа к Docker socket и кэшу Flutter: такие команды запускаются через Terminal.app.
