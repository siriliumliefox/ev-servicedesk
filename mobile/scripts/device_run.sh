#!/usr/bin/env bash
# Проверка на реальном iPhone (глава 18, DoD; ADR 0022 п. 4): стек backend из образа-кандидата, открытый в
# локальной сети, и release-сборка приложения на iPhone (бесплатная подпись Personal Team). Стек держится,
# пока не нажата Enter (или HOLD_SECONDS секунд); тестовый номер и код печатаются для ручного входа.
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
  cd "$1/mobile"
  flutter run --release -d "$2" --dart-define=API_BASE_URL="http://$3:$4" </dev/null >/tmp/ev-device-run.log 2>&1 &
  echo "Приложение собирается и устанавливается на iPhone (лог: /tmp/ev-device-run.log)"
  echo "API для iPhone: http://$3:$4"
  echo "Тестовый номер: ${E2E_PHONE#+375}  код: $E2E_CODE"
  if [ -n "${HOLD_SECONDS:-}" ]; then
    echo "Стек работает $HOLD_SECONDS с (HOLD_SECONDS)"; sleep "$HOLD_SECONDS"
  else
    read -r -p "Пройдите сценарий на iPhone и нажмите Enter, чтобы остановить стек… " _ </dev/tty
  fi
  kill %1 2>/dev/null || true
' _ "$ROOT" "$DEVICE" "$HOST" "$PORT"
