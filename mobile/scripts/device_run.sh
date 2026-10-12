#!/usr/bin/env bash
# Проверка на реальном iPhone (глава 18, DoD; ADR 0022 п. 4): стек backend из образа-кандидата, открытый в
# локальной сети, и release-сборка приложения на iPhone (бесплатная подпись Personal Team). Стек держится,
# пока не нажата Enter (или HOLD_SECONDS секунд); тестовый номер и код печатаются для ручного входа.
# Глава 19 (ADR 0023 п. 7): на стеке — 5 тестовых авто схемы агрегатов (seed), вход их номером; ожидаемые статусы —
# docs/specs/scheme_test_vehicles.json и таблица в отчёте главы.
# Запуск: mobile/scripts/device_run.sh [iPhone — имя или id из `flutter devices`]
# Нужны: Docker, Xcode с Apple ID (Personal Team), iPhone в «Режиме разработчика» и той же сети Wi-Fi.

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DEVICE="${1:-$(cd "$ROOT/mobile" && flutter devices --machine 2>/dev/null |
  python3 -c 'import json,sys; d=[x for x in json.load(sys.stdin) if x["targetPlatform"]=="ios" and not x["emulator"]]; print(d[0]["id"] if d else "")')}"
if [ -z "$DEVICE" ]; then
  echo "iPhone не найден: подключите кабелем или включите «Подключаться по сети» в Xcode → Devices" >&2
  exit 1
fi
HOST="$(scutil --get LocalHostName).local"
PORT="${INTEGRATION_PORT:-18080}"

docker build -q -t backend:smoke "$ROOT/backend" >/dev/null
# Переменные стека раскрывает внутренний bash — одинарные кавычки намеренно.
# shellcheck disable=SC2016
INTEGRATION_BIND=0.0.0.0 INTEGRATION_PORT="$PORT" "$ROOT/scripts/integration_stack.sh" backend:smoke -- bash -c '
  set -e
  (cd "$1/backend" && poetry run python scripts/seed_scheme_vehicles.py)
  cd "$1/mobile"
  echo "Сборка release для iPhone (лог: /tmp/ev-device-run.log)"
  flutter build ios --release --dart-define=API_BASE_URL="http://$3:$4" >/tmp/ev-device-run.log 2>&1
  xcrun devicectl device install app --device "$2" build/ios/iphoneos/Runner.app >>/tmp/ev-device-run.log 2>&1
  xcrun devicectl device process launch --device "$2" com.etsavtogomel.evServicedesk >>/tmp/ev-device-run.log 2>&1 ||
    echo "Не запустилось: на iPhone — Настройки → Основные → VPN и управление устройством → доверять разработчику"
  echo "Приложение установлено. API для iPhone: http://$3:$4"
  echo "Тестовый номер: ${E2E_PHONE#+375}  код: $E2E_CODE"
  echo "Схема агрегатов, 5 тестовых авто: номер ${E2E_SCHEME_PHONE#+375}  код: $E2E_CODE"
  if [ -n "${HOLD_SECONDS:-}" ]; then
    echo "Стек работает $HOLD_SECONDS с (HOLD_SECONDS)"; sleep "$HOLD_SECONDS"
  else
    read -r -p "Пройдите сценарий на iPhone и нажмите Enter, чтобы остановить стек… " _ </dev/tty
  fi
' _ "$ROOT" "$DEVICE" "$HOST" "$PORT"
