#!/usr/bin/env bash
# Проверка админ-панели владельцем в роли администратора (глава 22, DoD; ADR 0026 п. 18): стек backend из
# образа-кандидата, данные (администратор, 2 инженера с тикетом, клиент с Zeekr 001 и регламентом салонного
# фильтра, контрольный набор аналитики за март 2026 — backend/scripts/e2e_admin.py) и админ-панель в режиме
# API на http://127.0.0.1:5176 (тот же origin, прокси /v1 на стек). Пароли, номер и код клиента — только в
# файле ADMIN_SEED_FILE (0600), на экран не выводятся. MOBILE=1 — ещё и мобильное приложение в загруженном
# iOS Simulator (клиент: «светофор» после пересмотра регламента, новости, статьи). Стек и админ-панель
# работают до Ctrl+C; стек удаляется при выходе.
# Запуск: web-admin/scripts/admin_run.sh          (MOBILE=1 web-admin/scripts/admin_run.sh)
# Нужны: Docker, poetry-окружение backend, npm ci; для MOBILE=1 — Xcode и загруженный симулятор.

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
PORT="${INTEGRATION_PORT:-18080}"
WEB_PORT="${WEB_PORT:-5176}"
OUT="${ADMIN_SEED_FILE:-$HOME/.config/ev-servicedesk/admin.local}"
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
  (cd "$ROOT/backend" && poetry run python scripts/e2e_admin.py seed --out "$OUT")
  if [ -n "$SIMULATOR" ]; then
    echo "Мобильное приложение в симуляторе $SIMULATOR (лог: /tmp/ev-admin-run-mobile.log)"
    (cd "$ROOT/mobile" && flutter run -d "$SIMULATOR" --dart-define=API_BASE_URL="$API_BASE_URL" \
      >/tmp/ev-admin-run-mobile.log 2>&1 &)
  fi
  echo
  echo "Админ-панель: http://127.0.0.1:$WEB_PORT  (кабинет инженера для проверки отказа — тот же вход)"
  echo "Входы администратора и инженеров, номер и код клиента — в $OUT"
  echo "Чек-лист прогона — docs/reviews/ADMIN_PANEL_22.md. Остановить — Ctrl+C."
  echo
  cd "$ROOT/web-admin"
  VITE_API_BASE_URL=/v1 EV_API_PROXY="$API_BASE_URL" npx vite --host 127.0.0.1 --port "$WEB_PORT" --strictPort
' _ "$ROOT" "$OUT" "$WEB_PORT" "$SIMULATOR"
