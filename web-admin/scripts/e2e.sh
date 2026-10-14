#!/usr/bin/env bash
# E2E админ-панели локально (глава 22, ADR 0026 п. 15): стек backend из образа-кандидата, данные
# (backend/scripts/e2e_admin.py seed: сотрудники, клиент с авто и регламентом, контрольный набор
# аналитики) и Playwright: Chromium (как в CI), Firefox, WebKit (Safari). Стек удаляется при выходе.
# Сценарий «пользователи» меняет данные (блокировка, сброс пароля) — у каждого браузера свой набор (--sets 3).
# Запуск: web-admin/scripts/e2e.sh [аргументы playwright test, например --project=webkit]
# E2E_BACKEND_IMAGE — готовый образ backend (CI: backend:integration); без него собирается backend:smoke.
# Нужны: Docker, poetry-окружение backend, npm ci, npx playwright install chromium firefox webkit.

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
IMAGE="${E2E_BACKEND_IMAGE:-}"
if [ -z "$IMAGE" ]; then
  IMAGE=backend:smoke
  docker build -q -t "$IMAGE" "$ROOT/backend" >/dev/null
fi
# Переменные стека раскрывает внутренний bash — одинарные кавычки намеренно.
# shellcheck disable=SC2016
"$ROOT/scripts/integration_stack.sh" "$IMAGE" -- bash -c '
  set -e
  ROOT="$1"; shift
  SEED="$(mktemp)"
  (cd "$ROOT/backend" && poetry run python scripts/e2e_admin.py seed --out "$SEED" --sets 3)
  cd "$ROOT/web-admin"
  E2E_ADMIN_SEED="$SEED" npx playwright test "$@"
' _ "$ROOT" "$@"
