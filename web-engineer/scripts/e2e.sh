#!/usr/bin/env bash
# E2E веб-кабинета инженера локально во всех браузерах (глава 21, ADR 0025 п. 14): стек backend из
# образа-кандидата, данные (seed: набор из 3 тикетов на каждый браузер — клиент создаёт не больше 10
# тикетов в час) и Playwright: Chromium (как в CI), Firefox, WebKit (Safari). Стек удаляется при выходе.
# Запуск: web-engineer/scripts/e2e.sh [аргументы playwright test, например --project=webkit]
# Нужны: Docker, poetry-окружение backend, npm ci, npx playwright install chromium firefox webkit.

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
docker build -q -t backend:smoke "$ROOT/backend" >/dev/null
# Переменные стека раскрывает внутренний bash — одинарные кавычки намеренно.
# shellcheck disable=SC2016
"$ROOT/scripts/integration_stack.sh" backend:smoke -- bash -c '
  set -e
  ROOT="$1"; shift
  SEED="$(mktemp)"
  (cd "$ROOT/backend" && poetry run python scripts/e2e_engineer.py seed --out "$SEED" --board-tickets 0 --e2e-sets 3)
  cd "$ROOT/web-engineer"
  E2E_ENGINEER_SEED="$SEED" npx playwright test "$@"
' _ "$ROOT" "$@"
