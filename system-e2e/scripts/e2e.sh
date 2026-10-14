#!/usr/bin/env bash
# Межролевые E2E локально (глава 23, ADR 0027 п. 8): стек backend из образа, данные
# (backend/scripts/e2e_system.py seed: сотрудники, клиент X с авто на каждый браузер, клиент Y другой
# модели) и Playwright: Chromium, Firefox, WebKit. Стек удаляется при выходе.
# Запуск: system-e2e/scripts/e2e.sh [аргументы playwright test, например --project=webkit]
# E2E_BACKEND_IMAGE — готовый образ backend (CI: backend:integration или опубликованный по digest); без него
# собирается backend:smoke. Порты стека — INTEGRATION_PORT / INTEGRATION_S3_PORT (по умолчанию 18080 / 19000).
# Нужны: Docker, poetry-окружение backend, npm ci, npx playwright install chromium firefox webkit.

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
IMAGE="${E2E_BACKEND_IMAGE:-}"
if [ -z "$IMAGE" ]; then
  IMAGE=backend:smoke
  docker build -q -t "$IMAGE" "$ROOT/backend" >/dev/null
fi
export E2E_MEDIA_ORIGIN="${E2E_MEDIA_ORIGIN:-http://127.0.0.1:${INTEGRATION_S3_PORT:-19000}}"
# Переменные стека раскрывает внутренний bash — одинарные кавычки намеренно.
# shellcheck disable=SC2016
"$ROOT/scripts/integration_stack.sh" "$IMAGE" -- bash -c '
  set -e
  ROOT="$1"; shift
  SEED="$(mktemp)"
  (cd "$ROOT/backend" && poetry run python scripts/e2e_system.py seed --out "$SEED" --sets 3)
  cd "$ROOT/system-e2e"
  E2E_SYSTEM_SEED="$SEED" npx playwright test "$@"
' _ "$ROOT" "$@"
