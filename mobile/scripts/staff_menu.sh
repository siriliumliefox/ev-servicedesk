#!/usr/bin/env bash
# Меню инженера на работающем стеке (глава 20, ADR 0024 п. 12): ответ в чат тикета, решение, новость и акция —
# backend/scripts/e2e_support.py. Вызывается из device_run.sh и android_push_run.sh внутри
# scripts/integration_stack.sh (окружение API_BASE_URL, E2E_JOB_RUNNER). Пустая строка — выход из меню.
# Запуск: mobile/scripts/staff_menu.sh <корень репозитория>

set -uo pipefail

ROOT="${1:?корень репозитория}"
staff() { (cd "$ROOT/backend" && poetry run python scripts/e2e_support.py "$@"); }

while true; do
  echo
  echo "Инженер: <номер тикета> — ответить в чат; r <номер> — ответить и решить; n — новость и акция"
  read -r -p "Enter без команды — остановить стек: " cmd arg </dev/tty || break
  case "$cmd" in
    "") break ;;
    n) staff publish ;;
    r) staff reply --ticket "$arg" --text "Проблема решена. Если повторится — создайте новое обращение" \
         --status resolved ;;
    *[!0-9]*) echo "Не понял команду" ;;
    *) staff reply --ticket "$cmd" ;;
  esac
done
