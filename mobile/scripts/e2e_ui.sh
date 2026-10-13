#!/usr/bin/env bash
# UI E2E мобильного приложения (глава 18, ADR 0022 п. 2): integration_test в iOS Simulator против стека backend
# из образа-кандидата (scripts/integration_stack.sh). В CI не запускается: на macOS-раннерах GitHub нет Docker.
# Схема агрегатов (глава 19, ADR 0023 п. 7): перед тестами seed 5 тестовых авто, scheme_test сверяет экран с API.
# Клиентский сценарий (глава 20, ADR 0024 п. 1): статьи с деревом решений (e2e_support.py seed); инженер на Mac
# (e2e_support.py answer) ждёт тикет из дерева, отвечает в чат и публикует новость — support_flow_test.
# Запуск: mobile/scripts/e2e_ui.sh [симулятор]   (по умолчанию — первый запущенный)
# Нужны: Docker, Xcode с запущенным симулятором, poetry-окружение backend.

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DEVICE="${1:-$(xcrun simctl list devices booted | awk -F '[()]' '/Booted/ {print $2; exit}')}"
if [ -z "$DEVICE" ]; then
  echo "Нет запущенного симулятора: откройте Simulator или передайте имя/UDID" >&2
  exit 1
fi

docker build -q -t backend:smoke "$ROOT/backend" >/dev/null
# Переменные стека (API_BASE_URL, E2E_PHONE, E2E_SCHEME_PHONE, E2E_SUPPORT_PHONE, E2E_CODE) раскрывает
# внутренний bash — одинарные кавычки намеренно.
# shellcheck disable=SC2016
"$ROOT/scripts/integration_stack.sh" backend:smoke -- bash -c \
  'set -e
   (cd "$1/backend" && poetry run python scripts/seed_scheme_vehicles.py &&
    poetry run python scripts/e2e_support.py seed)
   (cd "$1/backend" && poetry run python scripts/e2e_support.py answer) & answer=$!
   cd "$1/mobile" && flutter test integration_test -d "$2" --dart-define=API_BASE_URL="$API_BASE_URL" \
     --dart-define=E2E_PHONE="$E2E_PHONE" --dart-define=E2E_SCHEME_PHONE="$E2E_SCHEME_PHONE" \
     --dart-define=E2E_SUPPORT_PHONE="$E2E_SUPPORT_PHONE" --dart-define=E2E_CODE="$E2E_CODE"
   wait "$answer"' _ "$ROOT" "$DEVICE"
