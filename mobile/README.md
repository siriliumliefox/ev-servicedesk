# EV-ServiceDesk — Mobile (Flutter)

## Платформы (ADR 0022)
- **iOS (iPhone)** — основная платформа, проверяется на устройстве.
- **Android** — собирается в CI (`flutter build apk --debug`); Android-устройства нет. Push в свёрнутом и закрытом
  приложении проверяется на эмуляторе с Google Play (глава 20, ADR 0024 п. 5).
- **macOS** — для разработки, вне DoD.

Bundle id / applicationId — `com.etsavtogomel.evServicedesk`.

## Режимы запуска
| Режим | Команда | Данные |
|---|---|---|
| Прототип | `flutter run` | фикстуры `PrototypeRepository`, панель «Демо» (главы 7, 9) |
| Реальный API | `flutter run --dart-define=API_BASE_URL=http://127.0.0.1:8000` | backend, `HttpClientRepository` (глава 18) |
| + push | то же и `--dart-define-from-file=firebase.local.json` | FCM; файл создаёт `../scripts/firebase_dev_setup.sh` (глава 20) |

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
../scripts/integration_stack.sh backend:smoke -- bash -c '(cd backend && poetry run python scripts/seed_scheme_vehicles.py && poetry run python scripts/e2e_support.py seed) && cd mobile && flutter test test_api_e2e'
```
(предварительно `docker build -t backend:smoke ../backend`). Данные сценария главы 20 — `docs/specs/support_flow.json`,
действия персонала (статьи, ответ инженера, новость) — `backend/scripts/e2e_support.py`.

Push в свёрнутом и закрытом приложении (глава 20): `scripts/android_push_run.sh` — Android-эмулятор, стек с
настоящим FCM, меню инженера в Terminal; сценарии — `docs/reviews/MOBILE_CLIENT_FLOWS_20.md`.

## Проверка на iPhone (бесплатная подпись Personal Team)
Один раз (действия владельца — Apple ID и настройки iPhone агент не вводит):
1. Xcode → Settings → Accounts → «+» → Apple ID (Personal Team появится автоматически).
2. iPhone — кабелем к Mac, «Доверять этому компьютеру»; Настройки → Конфиденциальность и безопасность →
   «Режим разработчика» → вкл., перезагрузка. В Xcode → Window → Devices and Simulators у iPhone —
   «Connect via network» (дальше можно без кабеля, в той же сети Wi-Fi).
3. ID Personal Team — в локальный `ios/Flutter/DeveloperTeam.xcconfig` (в git не попадает, в `project.pbxproj` команду
   не сохранять): `DEVELOPMENT_TEAM = <id>`; id — `defaults read com.apple.dt.Xcode | grep teamID`. Первый раз
   сертификат и профиль выпускает `xcodebuild … -allowProvisioningUpdates -allowProvisioningDeviceRegistration build`.

Прогон: `scripts/device_run.sh` — стек backend из образа-кандидата, открытый в локальной сети
(`http://<имя-mac>.local:18080`, `NSAllowsLocalNetworking`), release-сборка на iPhone, тестовый номер и код
на экране. При первом запуске на iPhone: Настройки → Основные → VPN и управление устройством → доверять
разработчику. Профиль бесплатной подписи действует 7 дней.

Сценарий: телефон → код → согласие → VIN → главный экран → карточка (пробег, история ТО) → перезапуск без SMS →
профиль → выход; повторить с профилем «Edge» (iPhone: Настройки → Разработчик → Network Link Conditioner).
Результат — в `docs/reviews/MOBILE_SKELETON_18.md`. Глава 20: клиентский сценарий (обучение → дерево решений →
тикет с фото → ответ инженера → новости) — чек-лист и меню инженера в `docs/reviews/MOBILE_CLIENT_FLOWS_20.md`.

## Структура
- `lib/main.dart` — точка входа: прототип или реальный API по `API_BASE_URL`
- `lib/app/` — состояние приложения (`AppState`, `AppScope`): сессия, авто, раздел; push (`PushService`)
- `lib/data/` — модели по `docs/openapi.yaml`, `ClientRepository`, `HttpClientRepository`, `PrototypeRepository`;
  вложения (`attachments.dart`), чат в реальном времени (`ticket_live.dart`)
- `lib/data/api/` — `ApiClient` (HTTP, ошибки, обновление токенов, PUT в S3), разбор JSON контракта, `TokenStore`
- `lib/push/` — `PushChannel` над firebase_messaging, отладочный экран push (глава 15)
- `lib/screens/` — онбординг, «Авто» (карточка авто), «Обучение», «Поддержка», «Новости» и центр уведомлений, профиль
- `lib/theme/`, `lib/ui/` — дизайн-система (глава 6), состояния загрузки/пусто/ошибка, панель «Демо»
- `test/` — дизайн-система, прототип, `ApiClient`, плохая сеть; `test_api_e2e/` — E2E API; `integration_test/` — UI E2E

Прототип — `docs/design/MOBILE_PROTOTYPE.md` (глава 7, ADR 0011). Вложения тикета, чат в реальном времени, push и
центр уведомлений — глава 20 (ADR 0024), схема агрегатов — глава 19. Отладочный экран push (глава 15) — `lib/main_push_debug.dart`, `docs/NOTIFICATIONS_E2E.md`.
