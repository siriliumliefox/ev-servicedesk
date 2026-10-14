#!/usr/bin/env bash
# UI E2E мобильного приложения (глава 18, ADR 0022 п. 2): integration_test в iOS Simulator против стека backend
# из образа-кандидата (scripts/integration_stack.sh); шаги внутри стека — mobile/scripts/e2e_ui_tests.sh. На
# macOS-раннерах GitHub нет Docker — в CI те же тесты идут на Android-эмуляторе (глава 23, ADR 0027 п. 4).
# Схема агрегатов (глава 19, ADR 0023 п. 7): перед тестами seed 5 тестовых авто, scheme_test сверяет экран с API.
# Клиентский сценарий (глава 20, ADR 0024 п. 1): статьи с деревом решений (e2e_support.py seed); инженер на Mac
# (e2e_support.py answer) ждёт тикет из дерева, отвечает в чат и публикует новость — support_flow_test.
# Центр уведомлений (глава 23, ADR 0027 п. 15): e2e_support.py notify — клиент с напоминанием о ТО и прошивкой,
# notifications_test входит им и проверяет ленту.
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
"$ROOT/scripts/integration_stack.sh" backend:smoke -- "$ROOT/mobile/scripts/e2e_ui_tests.sh" "$DEVICE"
