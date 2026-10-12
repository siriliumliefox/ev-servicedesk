#!/usr/bin/env bash
# Записывает JSON-ключ сервисного аккаунта Firebase в GitHub Environments (Глава 15, ADR 0019).
# Запускает ВЛАДЕЛЕЦ: путь к скачанному из консоли Firebase файлу ключа вводится с клавиатуры,
# содержимое проверяется (project_id, client_email, private_key), нигде не печатается и не
# попадает в argv — передаётся в `gh secret set` через stdin.
#
#   FCM_SERVICE_ACCOUNT_JSON — Project settings → Service accounts → Generate new private key
#
# После записи файл ключа удалите из «Загрузок» — ключ хранится только в GitHub Environments
# (и в локальном .env для проверки на устройстве, docs/NOTIFICATIONS_E2E.md).
# Запуск:  ./scripts/set-fcm-secret.sh [staging] [production]   (по умолчанию — оба)

set -euo pipefail

command -v gh >/dev/null || { echo "Нужен GitHub CLI: brew install gh && gh auth login"; exit 1; }

REPO="${GITHUB_REPO:-$(gh repo view --json nameWithOwner --jq .nameWithOwner)}"
[ $# -gt 0 ] || set -- staging production

read -r -p "Путь к JSON-ключу сервисного аккаунта Firebase: " key_path
key_path="${key_path/#\~/$HOME}"
[ -f "$key_path" ] || { echo "Файл не найден"; exit 1; }
# Проверка без вывода значений; на выходе — JSON одной строкой.
compact="$(python3 -c '
import json, sys
data = json.load(open(sys.argv[1], encoding="utf-8"))
missing = [k for k in ("project_id", "client_email", "private_key") if not data.get(k)]
if data.get("type") != "service_account" or missing:
    sys.exit("Это не ключ сервисного аккаунта Firebase (нет: " + ", ".join(missing or ["type"]) + ")")
print(json.dumps(data, separators=(",", ":")))
' "$key_path")"
project="$(printf '%s' "$compact" | python3 -c 'import json,sys; print(json.load(sys.stdin)["project_id"])')"

for env_name in "$@"; do
  printf '%s' "$compact" | gh secret set FCM_SERVICE_ACCOUNT_JSON --repo "$REPO" --env "$env_name"
  gh variable set PUSH_PROVIDER --repo "$REPO" --env "$env_name" --body fcm
  echo "→ ${env_name}: FCM_SERVICE_ACCOUNT_JSON (secret, проект ${project}), PUSH_PROVIDER=fcm (variable)"
done
unset compact
