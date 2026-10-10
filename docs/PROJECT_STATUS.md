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
| 05 | Алгоритм «светофор» и регламенты ТО | DONE | Issue #31, PR #32 (`952fe33` в `develop`), ADR 0009; CI на PR зелёный: `ci-gate`, backend, web ×2, mobile, docs, secret-scan. Спецификация `docs/specs/AGGREGATE_STATUS_ALGORITHM.md` + сценарии `docs/specs/aggregate_status_scenarios.yaml` (S01–S19, R01–R04; границы 69/69,99/70/100/100,01/101%, `unknown` без истории) приложены к контракту: `externalDocs` тега `Aggregates`, OpenAPI 1.1.0. Пороги — `aggregate_status_thresholds` (миграция `0005`), `GET/PUT /aggregate-status-thresholds`, `AggregateStatus.remaining_days`; доменная функция `backend/app/domain/aggregates`, `tests/domain` (сценарии + синхронность с таблицами спецификации). Сервис и API — глава 12 |
| 06 | Дизайн-система | PARTIAL | Issue #34 (открыт), PR #35 (`40e1f6d` в `develop`), ADR 0010, `docs/design/DESIGN_SYSTEM.md`; CI на PR зелёный: `ci-gate`, backend, web ×2, mobile, docs, secret-scan (`test:tokens` 100/100 в web-ci). Токены `design/tokens.json` → `tokens.css` (Tailwind v4) / `tokens.g.dart` (Flutter); контраст WCAG обеих тем, сетка 4, тап-зоны ≥ 44 — автотесты; бренд ETS AUTO `#f9ce12`, Inter; веб (`StatusBadge`, `Button`, `TextField`, `Card`, тёмная тема инженера) и Flutter (`evTheme`, `StatusBadge`, `EvBottomNav`). Figma: [EV-ServiceDesk Design System](https://www.figma.com/design/mgvOfQ9AizhhPMpBhxA3b5) — переменные, стили, компоненты собраны. **DoD не выполнен:** библиотека Figma не опубликована — BLOCKED тарифом Starter (вариант B, Education запрошен); не собрана страница `Engineer · Dark` (лимит MCP, `design/figma/engineer-dark.js`); проверка Stark в Figma — NOT RUN (владелец) |
| 07 | Прототип мобильного приложения клиента | DONE | Issue #37, PR #38 (`272d3f5` в `develop`), ADR 0011; CI на PR зелёный: `ci-gate`, mobile, docs, secret-scan (backend, web — skipped). Кликабельный прототип на Flutter с фикстурами по OpenAPI v1 (`ClientRepository` / `PrototypeRepository`) вместо Figma (тариф Starter): онбординг (телефон → SMS-код + согласие ПД → VIN), «Авто» (переключатель, схема агрегатов, карточка агрегата), «Обучение», «Поддержка» (деревья решений → тикет, чат), «Новости» (уведомления); несколько авто, пустые состояния, «нет сети»; навигация по ТЗ — 4 пункта. `flutter test` 29 PASS: правило 3-х кликов (1/2/2/3 тапа), 360 px, тап-зоны ≥ 44. `docs/design/MOBILE_PROTOTYPE.md`. **DoD:** прототип утверждён владельцем проекта 2026-10-10 |
| 08 | Прототип веб-кабинета инженера и админ-панели | DONE | Issue #40, PR #41 (`3693617` в `develop`), ADR 0012; CI на PR зелёный: `ci-gate`, web ×2, docs, secret-scan (backend, mobile — skipped). Кликабельные прототипы на React + Tailwind с фикстурами по OpenAPI v1 (`EngineerRepository` / `AdminRepository` / `PrototypeRepository` в `web-shared`) вместо Figma (тариф Starter). Инженер: канбан с фильтрами SLA (из `sla_due_at`/`is_overdue`), исполнителя и категории; карточка тикета — claim, статусы, переписка, быстрые ответы из базы знаний, авто клиента (агрегаты, история ТО); тёмная тема по умолчанию. Админ: дашборд `/analytics/*`, конструктор регламентов ТО (пересмотр с историей, пороги, агрегаты), конструктор статей и дерева решений с проверкой, публикации и прошивки. `npm test` 71 PASS (web-shared 39, web-engineer 14, web-admin 18): подсчёт кликов (просроченные — 1, авто клиента — 1, взять в работу — 2, статус — 2, ответ из базы знаний — 3); Full HD 1920×1080 без горизонтальной прокрутки, скриншоты `docs/design/web-prototype/`. `docs/design/WEB_PROTOTYPE.md`. Контракт v1 не менялся; открытые вопросы (ADR 0012, п. 5) — главы 13–15. **DoD:** прототипы утверждены владельцем проекта 2026-10-10 |
| 09–28 | см. `MASTER_CHECKLIST.md` | NOT_STARTED | — |

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
