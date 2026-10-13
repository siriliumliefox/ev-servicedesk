#!/usr/bin/env bash
# Push в свёрнутом и закрытом приложении (глава 20, ADR 0024 п. 5): Android-эмулятор с Google Play и настоящий FCM.
# Стек backend из образа-кандидата с ключом Firebase (scripts/firebase_dev_setup.sh → FCM_SERVICE_ACCOUNT_FILE),
# debug-сборка с FIREBASE_* (mobile/firebase.local.json) на эмуляторе; эмулятор ходит к стеку Mac по 10.0.2.2.
# Пока стек работает — меню инженера (staff_menu.sh): ответ в чат → push «Новое сообщение по обращению»,
# n → push новости и акции. Сценарии проверки — docs/reviews/MOBILE_CLIENT_FLOWS_20.md.
# Запуск: mobile/scripts/android_push_run.sh [AVD]   (по умолчанию — первый из `emulator -list-avds`)
# Нужны: Docker, Android SDK с эмулятором (образ google_apis_playstore), конфигурация Firebase владельца.

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
SDK="${ANDROID_HOME:-$HOME/Library/Android/sdk}"
ADB="$SDK/platform-tools/adb"
KEY="${FCM_SERVICE_ACCOUNT_FILE:-$HOME/.config/ev-servicedesk/fcm-service-account.json}"
if [ ! -f "$KEY" ] || [ ! -f "$ROOT/mobile/firebase.local.json" ]; then
  echo "Нет конфигурации Firebase — запустите scripts/firebase_dev_setup.sh" >&2
  exit 1
fi

if ! "$ADB" devices | grep -q '^emulator-'; then
  AVD="${1:-$("$SDK/emulator/emulator" -list-avds | head -1)}"
  echo "Запуск эмулятора $AVD (лог: /tmp/ev-emulator.log)"
  "$SDK/emulator/emulator" -avd "$AVD" -no-snapshot-save >/tmp/ev-emulator.log 2>&1 &
  "$ADB" wait-for-device
  until [ "$("$ADB" shell getprop sys.boot_completed | tr -d '\r')" = 1 ]; do sleep 2; done
fi
DEVICE="$("$ADB" devices | awk '/^emulator-/ {print $1; exit}')"

docker build -q -t backend:smoke "$ROOT/backend" >/dev/null
# Переменные стека раскрывает внутренний bash — одинарные кавычки намеренно.
# shellcheck disable=SC2016
FCM_SERVICE_ACCOUNT_FILE="$KEY" INTEGRATION_S3_PUBLIC="http://10.0.2.2:${INTEGRATION_S3_PORT:-19000}" \
  "$ROOT/scripts/integration_stack.sh" backend:smoke -- bash -c '
  set -e
  (cd "$1/backend" && poetry run python scripts/e2e_support.py seed)
  cd "$1/mobile"
  api="${API_BASE_URL/127.0.0.1/10.0.2.2}"
  echo "Сборка debug APK (лог: /tmp/ev-android-run.log)"
  flutter build apk --debug --dart-define=API_BASE_URL="$api" --dart-define-from-file=firebase.local.json \
    >/tmp/ev-android-run.log 2>&1
  "$3" -s "$2" install -r build/app/outputs/flutter-apk/app-debug.apk >>/tmp/ev-android-run.log 2>&1
  "$3" -s "$2" shell pm grant com.etsavtogomel.evServicedesk android.permission.POST_NOTIFICATIONS || true
  "$3" -s "$2" shell monkey -p com.etsavtogomel.evServicedesk -c android.intent.category.LAUNCHER 1 >/dev/null
  echo "Приложение на $2. API для эмулятора: $api"
  echo "Номер: ${E2E_SUPPORT_PHONE#+375}  код: $E2E_CODE"
  if [ -n "${HOLD_SECONDS:-}" ]; then
    echo "Стек работает $HOLD_SECONDS с (HOLD_SECONDS)"; sleep "$HOLD_SECONDS"
  else
    "$1/mobile/scripts/staff_menu.sh" "$1"
  fi
' _ "$ROOT" "$DEVICE" "$ADB"
