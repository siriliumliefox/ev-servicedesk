#!/usr/bin/env bash
# Стенд исследовательского тестирования (глава 23, ADR 0027 п. 11): стек backend из образа-кандидата, данные
# межролевых сценариев (backend/scripts/e2e_system.py: администратор, инженер, клиент X с Zeekr 001 и
# изношенными фильтрами, клиент Y другой модели) и статьи базы знаний с деревом решений (e2e_support.py seed),
# кабинет инженера и админ-панель — production-сборки (`/v1`, CSP) в `vite preview`. Работает до Ctrl+C, стек
# удаляется при выходе. Входы сотрудников, номера и SMS-код клиентов — только в EXPLORE_SEED_FILE (0600);
# клиент — мобильное приложение (номер и код из файла) или API (Swagger — http://127.0.0.1:18080/docs).
# Задания сессий — docs/reviews/E2E_REGRESSION_23.md, «Исследовательское тестирование».
# Запуск: scripts/explore_run.sh   (порты: ENGINEER_PORT 5177, ADMIN_PORT 5178, INTEGRATION_PORT 18080)
# Нужны: Docker, poetry-окружение backend, npm ci.

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUT="${EXPLORE_SEED_FILE:-$HOME/.config/ev-servicedesk/explore.local}"
mkdir -p "$(dirname "$OUT")"
docker build -q -t backend:smoke "$ROOT/backend" >/dev/null
# Переменные стека раскрывает внутренний bash — одинарные кавычки намеренно.
# shellcheck disable=SC2016
"$ROOT/scripts/integration_stack.sh" backend:smoke -- bash -c '
  set -e
  ROOT="$1"; OUT="$2"; ENGINEER_PORT="$3"; ADMIN_PORT="$4"
  (cd "$ROOT/backend" &&
    poetry run python scripts/e2e_system.py seed --out "$OUT" --sets 1 &&
    poetry run python scripts/e2e_support.py seed)
  export VITE_API_BASE_URL=/v1 EV_API_PROXY="$API_BASE_URL"
  export VITE_MEDIA_ORIGIN="http://127.0.0.1:${INTEGRATION_S3_PORT:-19000}"
  # Сборки — во временном каталоге стенда. serve работает в фоновой подоболочке и заменяет её vite через exec:
  # $! — сам vite, и при выходе стенда он останавливается, а не остаётся держать порт.
  DIST="$(mktemp -d)"
  VITE="$ROOT/node_modules/.bin/vite"
  serve() {  # приложение, порт: production-сборка и vite preview
    cd "$ROOT/$1" && "$VITE" build --outDir "$DIST/$1" >/dev/null &&
      exec "$VITE" preview --outDir "$DIST/$1" --host 127.0.0.1 --port "$2" --strictPort
  }
  serve web-engineer "$ENGINEER_PORT" & engineer=$!
  serve web-admin "$ADMIN_PORT" & admin=$!
  trap "kill $engineer $admin 2>/dev/null || true; rm -rf $DIST" EXIT
  echo
  echo "Кабинет инженера: http://127.0.0.1:$ENGINEER_PORT   Админ-панель: http://127.0.0.1:$ADMIN_PORT"
  echo "Входы сотрудников, номера и код клиентов — в $OUT. Остановить — Ctrl+C."
  echo
  wait
' _ "$ROOT" "$OUT" "${ENGINEER_PORT:-5177}" "${ADMIN_PORT:-5178}"
