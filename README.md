# EV-ServiceDesk

Service Desk система с модулем «Цифровой паспорт автомобиля» для владельцев
электромобилей (Zeekr, BYD, Li Auto). Заказчик — ООО «ЕТСавтоГомель».

Разработка ведётся по мастер-чек-листу (28 глав, 5 блоков) — см. `docs/`.

## Структура репозитория

| Папка | Технологии | Статус |
|---|---|---|
| `backend/` | Python 3.12, FastAPI, PostgreSQL, SQLAlchemy, Alembic | ✅ каркас собран, тесты зелёные |
| `web-engineer/` | React 18, TypeScript, Vite, Tailwind | ✅ каркас собран |
| `web-admin/` | React 18, TypeScript, Vite, Tailwind | ✅ каркас собран |
| `web-shared/` | Общие компоненты веб-панелей (npm workspace) | ✅ используется в обеих панелях |
| `mobile/` | Flutter — таргеты iOS + macOS (не Android на первом этапе) | ⚠️ написан вручную, не собирался — см. `mobile/README.md` |
| `docs/` | Контракт API, ERD, DDL, приложения к ТЗ | ✅ |

## Целевая среда
Клиентское приложение запускается на **iPhone (iOS) и MacBook (macOS)**.
Разработка и тестирование — **MacBook Pro M5 Pro** (Apple Silicon). Android —
не первый этап (Flutter позволяет добавить позже без переписывания).

## Полная настройка на MacBook (с нуля)
`docs/MACOS_SETUP.md` — пошаговая инструкция: что установить, как создать
GitHub-репозиторий и запушить этот каркас, как поднять и проверить каждую
часть локально, как настроить branch protection и Environments. Начните
отсюда, если ещё ничего не настроено.

## Быстрый старт (локально)

### Backend
```bash
cd backend
poetry install
poetry run uvicorn app.main:app --reload
poetry run pytest
```

### Web (инженер/админ)
```bash
npm install                 # из корня — поднимает оба workspace + web-shared
npm run dev --workspace web-engineer
npm run dev --workspace web-admin
```

### Mobile
См. предупреждение в `mobile/README.md` — требуется локальная проверка `flutter analyze`/`flutter test` перед использованием.

## Контракт API
`docs/openapi.yaml` — источник истины. `docs/EV_ServiceDesk_SwaggerUI.html` — открыть в браузере для интерактивной документации (работает офлайн).

Версия **1.0.0 заморожена** — правила изменений и проверки в ADR 0007.

```bash
npm run mock        # mock-сервер Prism: http://localhost:4010 (любой Bearer-токен)
npm run lint:api    # Spectral (.spectral.yaml)
npm run test:mock   # smoke-тест mock-сервера клиентом web-shared
npm run gen:api     # типы web-shared/src/api/schema.ts из openapi.yaml
```

Клиент для веб-панелей: `createApiClient` из `@ev-servicedesk/web-shared` (адрес — `VITE_API_BASE_URL`, по умолчанию mock).

## Окружения и секреты
`docs/ENVIRONMENTS.md` — модель local/dev/staging/production, разделение секретов, настройка GitHub Environments со «стоп-краном» перед production.

## Ветвление и код-ревью
`CONTRIBUTING.md` — git-flow, процесс PR, текущая политика ревью.
