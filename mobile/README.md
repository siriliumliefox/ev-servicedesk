# EV-ServiceDesk — Mobile (Flutter)

## Платформы (ADR 0022)
- **iOS (iPhone)** — основная платформа, проверяется на устройстве.
- **Android** — собирается в CI (`flutter build apk --debug`); Android-устройства нет, на устройстве не проверяется.
- **macOS** — для разработки, вне DoD.

Bundle id / applicationId — `com.etsavtogomel.evServicedesk`.

## Режимы запуска
| Режим | Команда | Данные |
|---|---|---|
| Прототип | `flutter run` | фикстуры `PrototypeRepository`, панель «Демо» (главы 7, 9) |
| Реальный API | `flutter run --dart-define=API_BASE_URL=http://127.0.0.1:8000` | backend, `HttpClientRepository` (глава 18) |

`API_BASE_URL` — адрес backend без `/v1`. Из iOS Simulator `127.0.0.1` — это Mac.
Локальный backend: `docker compose up -d` и `uvicorn` (см. корневой `README.md`) или стек главы 17.

## Сессия (ADR 0022 п. 6, 7)
- refresh-токен — в Keychain/Keystore (`flutter_secure_storage`), access — только в памяти;
- при первом запуске после установки хранилище очищается (Keychain переживает удаление приложения);
- параллельные 401 — один запрос `/auth/refresh`; refresh автоматически не повторяется: повтор уже
  использованного токена backend считает кражей и завершает все сессии;
- без сети сессия не завершается — главный экран показывает «Нет подключения» и «Повторить».

## Проверки
```bash
flutter analyze && flutter test                 # unit, виджеты, плохая сеть, прототип
scripts/e2e_ui.sh                               # UI E2E в iOS Simulator против стека backend (Docker)
```
E2E на уровне API (`test_api_e2e/`) запускается в CI (`mobile-e2e.yml`) и локально:
```bash
../scripts/integration_stack.sh backend:smoke -- bash -c 'cd mobile && flutter test test_api_e2e'
```
(предварительно `docker build -t backend:smoke ../backend`).

## Проверка на iPhone (бесплатная подпись Personal Team)
1. iPhone и Mac — в одной сети Wi-Fi; на iPhone включён «Режим разработчика» (Настройки → Конфиденциальность).
2. Backend на Mac: стек главы 17 или `uvicorn` на `0.0.0.0:8000`. Тестовый номер и код — `SMS_TEST_PHONES`/`SMS_TEST_CODE`
   в `.env` (ADR 0021 п. 6) или реальная SMS.
3. `open ios/Runner.xcworkspace` → Runner → Signing & Capabilities → Team: ваш Apple ID (Personal Team).
4. `flutter run -d <iPhone> --dart-define=API_BASE_URL=http://<имя-mac>.local:8000`
   (`NSAllowsLocalNetworking` разрешает http только в локальной сети). На iPhone: Настройки → Основные →
   VPN и управление устройством → доверять разработчику. Профиль бесплатной подписи действует 7 дней.
5. Сценарий: телефон → код → согласие → VIN → главный экран → карточка (пробег, история ТО) →
   перезапуск без SMS → профиль → выход; повторить при «Edge» в Network Link Conditioner.
   Результат — в `docs/reviews/MOBILE_SKELETON_18.md`.

## Структура
- `lib/main.dart` — точка входа: прототип или реальный API по `API_BASE_URL`
- `lib/app/` — состояние приложения (`AppState`, `AppScope`): сессия, авто, выбранное авто
- `lib/data/` — модели по `docs/openapi.yaml`, `ClientRepository`, `HttpClientRepository`, `PrototypeRepository`
- `lib/data/api/` — `ApiClient` (HTTP, ошибки, обновление токенов), `TokenStore`, тексты ошибок
- `lib/screens/` — онбординг, «Авто» (карточка авто), «Обучение», «Поддержка», «Новости», профиль
- `lib/theme/`, `lib/ui/` — дизайн-система (глава 6), состояния загрузки/пусто/ошибка, панель «Демо»
- `test/` — дизайн-система, прототип, `ApiClient`, плохая сеть; `test_api_e2e/` — E2E API; `integration_test/` — UI E2E

Прототип — `docs/design/MOBILE_PROTOTYPE.md` (глава 7, ADR 0011). Вложения тикета и чат в реальном времени — глава 20,
схема агрегатов — глава 19. Отладочный экран push (глава 15) — `lib/main_push_debug.dart`, `docs/NOTIFICATIONS_E2E.md`.
