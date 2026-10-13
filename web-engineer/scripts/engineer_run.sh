#!/usr/bin/env bash
# Проверка веб-кабинета инженера владельцем в двух ролях (глава 21, DoD; ADR 0025 п. 15): стек backend из
# образа-кандидата, данные (2 инженера, клиент с авто, 6 тикетов, статья для быстрого ответа —
# backend/scripts/e2e_engineer.py) и кабинет в режиме API на http://127.0.0.1:5175 (тот же origin, прокси
# /v1 на стек). Пароли инженеров, номер и код клиента — только в файле ENGINEER_SEED_FILE (0600), на экран
# не выводятся. MOBILE=1 — ещё и мобильное приложение в загруженном iOS Simulator (клиент тикетов, вход
# по номеру и коду из файла). Стек и кабинет работают до Ctrl+C; стек удаляется при выходе.
# Запуск: web-engineer/scripts/engineer_run.sh          (MOBILE=1 web-engineer/scripts/engineer_run.sh)
# Нужны: Docker, poetry-окружение backend, npm ci; для MOBILE=1 — Xcode и загруженный симулятор.

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
PORT="${INTEGRATION_PORT:-18080}"
WEB_PORT="${WEB_PORT:-5175}"
OUT="${ENGINEER_SEED_FILE:-$HOME/.config/ev-servicedesk/engineers.local}"
SIMULATOR=""
if [ "${MOBILE:-0}" = "1" ]; then
  SIMULATOR="$(xcrun simctl list devices booted | awk -F '[()]' '/Booted/ {print $2; exit}')"
  [ -n "$SIMULATOR" ] || { echo "MOBILE=1: загрузите iOS Simulator (open -a Simulator)" >&2; exit 1; }
fi

docker build -q -t backend:smoke "$ROOT/backend" >/dev/null
# Переменные стека раскрывает внутренний bash — одинарные кавычки намеренно.
# shellcheck disable=SC2016
INTEGRATION_PORT="$PORT" "$ROOT/scripts/integration_stack.sh" backend:smoke -- bash -c '
  set -e
  ROOT="$1"; OUT="$2"; WEB_PORT="$3"; SIMULATOR="$4"
  (cd "$ROOT/backend" && poetry run python scripts/e2e_engineer.py seed --out "$OUT")
  if [ -n "$SIMULATOR" ]; then
    echo "Мобильное приложение в симуляторе $SIMULATOR (лог: /tmp/ev-engineer-run-mobile.log)"
    (cd "$ROOT/mobile" && flutter run -d "$SIMULATOR" --dart-define=API_BASE_URL="$API_BASE_URL" \
      >/tmp/ev-engineer-run-mobile.log 2>&1 &)
  fi
  echo
  echo "Кабинет инженера: http://127.0.0.1:$WEB_PORT  (инженер 1 — обычное окно, инженер 2 — инкогнито)"
  echo "Входы инженеров, номер и код клиента — в $OUT"
  echo "Чек-лист прогона — docs/reviews/ENGINEER_WEB_21.md. Остановить — Ctrl+C."
  echo
  cd "$ROOT/web-engineer"
  VITE_API_BASE_URL=/v1 VITE_MEDIA_ORIGIN="http://127.0.0.1:${INTEGRATION_S3_PORT:-19000}" EV_API_PROXY="$API_BASE_URL" \
    npx vite --host 127.0.0.1 --port "$WEB_PORT" --strictPort
' _ "$ROOT" "$OUT" "$WEB_PORT" "$SIMULATOR"
