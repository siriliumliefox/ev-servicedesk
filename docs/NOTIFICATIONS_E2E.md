# Push на реальном iPhone — проверка в главе 27

**Выполняется в главе 27** (бета-пилот): проверка на реальном устройстве перенесена из главы 15
решением владельца — ADR 0019 п. 20. Платный Apple Developer нужен там же для TestFlight.
В главе 15 сценарии прогнаны на локальном стеке без отправки в FCM. Код и автотесты готовы;
эта инструкция — для шагов, которые может сделать только владелец: аккаунт Apple, Firebase,
ключи и телефон.

Сценарии:

1. **Прошивка модели X** — push у владельца Zeekr 001 (телефон), у владельца Voyah Free — нет.
2. **Напоминание о ТО** — «просроченный» салонный фильтр → push «Пора на ТО».
3. **Новость** — push, запись в ленте, нажатие на push → `opened` и `read` в журнале.

В каждом сценарии push должен прийти **меньше чем за 10 с**.

## 1. Один раз: Apple Developer и Firebase

1. Оформить **Apple Developer Program** ($99/год). Без него APNs недоступен и FCM-токена на iPhone
   не будет.
2. developer.apple.com → Certificates, Identifiers & Profiles → **Keys** → «+» → Apple Push
   Notifications service (APNs) → скачать `AuthKey_XXXXXXXXXX.p8`. Записать Key ID и Team ID.
3. console.firebase.google.com → создать проект (например `ev-servicedesk`) → добавить
   **iOS-приложение** с Bundle ID `com.etsavtogomel.evServicedesk` → скачать
   `GoogleService-Info.plist`. В репозиторий его **не класть** (он в `.gitignore`).
4. Firebase → Project settings → **Cloud Messaging** → Apple app configuration → загрузить
   `.p8`, указать Key ID и Team ID.
5. Firebase → Project settings → **Service accounts** → Generate new private key → JSON-ключ.
6. Записать ключ в GitHub Environments:

   ```bash
   ./scripts/set-fcm-secret.sh staging production
   ```

   После этого файл JSON-ключа удалить из «Загрузок».
7. Xcode: открыть `mobile/ios/Runner.xcworkspace` → Runner → **Signing & Capabilities** →
   выбрать платную команду → «+ Capability» → **Push Notifications**. Xcode создаст
   `Runner.entitlements` (`aps-environment`). Изменения проекта закоммитить.

## 2. Локальный стенд (тот же код, что в `backend:staging`)

Staging-сервера нет до главы 26 (ADR 0008), поэтому backend и worker поднимаются на Mac из того же
коммита, что и образ `backend:staging`. Включается `ENVIRONMENT=local`, чтобы был доступен
отладочный маршрут SMS-кода. В `.env` (не в git) добавить:

```
PUSH_PROVIDER=fcm
FCM_SERVICE_ACCOUNT_JSON=<содержимое JSON-ключа одной строкой>
ACCESS_TOKEN_TTL_SECONDS=86400
```

```bash
(cd backend && poetry run alembic upgrade head)
```

```bash
docker compose --profile full up -d --build backend notifications-worker
```

iPhone и Mac — в одной Wi-Fi сети.

## 3. Приложение на iPhone

```bash
python3 scripts/push_e2e.py setup --plist ~/Downloads/GoogleService-Info.plist
```

```bash
cd mobile && flutter run -t lib/main_push_debug.dart --dart-define-from-file=push_e2e.local.json
```

На телефоне разрешить уведомления и доступ к локальной сети. На экране «Push: проверка на
устройстве» должно появиться «Токен: зарегистрирован (201)».

## 4. Сценарии

```bash
python3 scripts/push_e2e.py firmware
```

```bash
python3 scripts/push_e2e.py reminder
```

```bash
python3 scripts/push_e2e.py news
```

В сценарии `news` нажмите на баннер push: скрипт дождётся `opened` и `read` в журнале.

Для каждого сценария записать в `PROJECT_STATUS.md` (глава 15): время публикации из вывода
скрипта, время получения и «задержку … мс» с отладочного экрана, скриншот экрана.
«Задержка» — от момента, когда FCM принял сообщение, до получения на телефоне. Полное время от
публикации — разница между временем публикации в выводе скрипта и временем получения на экране
(часы Mac и iPhone синхронизированы по NTP).

## Если что-то не так

| Симптом | Причина |
|---|---|
| «нет токена (APNs/разрешение?)» | нет Push Notifications capability, бесплатная команда или уведомления запрещены |
| «backend недоступен» | телефон не видит Mac: другая сеть, фаервол macOS, не разрешена локальная сеть |
| «ошибка регистрации: HTTP 401» | истёк access-токен — повторить `setup` (и проверить `ACCESS_TOKEN_TTL_SECONDS`) |
| доставок 0, ошибок 1 | в логе worker `error_code`: `THIRD_PARTY_AUTH_ERROR` — APNs-ключ в Firebase; `SENDER_ID_MISMATCH` — plist и JSON-ключ из разных проектов |

Логи worker:

```bash
docker compose --profile full logs -f notifications-worker
```
