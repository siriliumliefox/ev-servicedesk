#!/usr/bin/env bash
# Шаг UI E2E мобильного приложения внутри стека backend (команда после «--» scripts/integration_stack.sh):
# данные схемы агрегатов (глава 19), статьи поддержки (глава 20) и клиент центра уведомлений (глава 23), инженер
# на хосте в фоне (e2e_support.py answer) и integration_test на устройстве. Общий для iOS Simulator
# (mobile/scripts/e2e_ui.sh) и Android-эмулятора в CI (.github/workflows/mobile-ui-e2e.yml, ADR 0027 п. 4).
# Запуск: e2e_ui_tests.sh <устройство> [адрес хоста для устройства, по умолчанию 127.0.0.1; Android — 10.0.2.2]
# Окружение стека: API_BASE_URL, E2E_PHONE, E2E_SCHEME_PHONE, E2E_SUPPORT_PHONE, E2E_NOTIFY_PHONE, E2E_CODE,
# E2E_JOB_RUNNER. Presigned URL MinIO для устройства — INTEGRATION_S3_PUBLIC при запуске стека.

set -euo pipefail

DEVICE="${1:?Укажите устройство flutter (-d)}"
HOST="${2:-127.0.0.1}"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

(cd "$ROOT/backend" &&
  poetry run python scripts/seed_scheme_vehicles.py &&
  poetry run python scripts/e2e_support.py seed &&
  poetry run python scripts/e2e_support.py notify)
(cd "$ROOT/backend" && poetry run python scripts/e2e_support.py answer) &
answer=$!

cd "$ROOT/mobile"
flutter test integration_test -d "$DEVICE" \
  --dart-define=API_BASE_URL="${API_BASE_URL/127.0.0.1/$HOST}" \
  --dart-define=E2E_PHONE="$E2E_PHONE" --dart-define=E2E_SCHEME_PHONE="$E2E_SCHEME_PHONE" \
  --dart-define=E2E_SUPPORT_PHONE="$E2E_SUPPORT_PHONE" --dart-define=E2E_NOTIFY_PHONE="$E2E_NOTIFY_PHONE" \
  --dart-define=E2E_CODE="$E2E_CODE"
wait "$answer"
