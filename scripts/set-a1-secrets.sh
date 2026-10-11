#!/usr/bin/env bash
# Записывает учётные данные A1 «Smart-рассылка» в GitHub Environments (Глава 10, ADR 0013).
# Запускает ВЛАДЕЛЕЦ: значения вводятся с клавиатуры (ключ — скрыто), нигде не печатаются
# и не попадают в argv — передаются в `gh secret set` через stdin.
#
#   SMS_PROVIDER_USER     — логин кабинета (msisdn, цифры)          → secret
#   SMS_PROVIDER_API_KEY  — «Настройки» → API key                   → secret
#   SMS_SENDER            — одобренное альфа-имя (≤ 11 символов)     → variable окружения
#
# Включение A1 (SMS_PROVIDER=a1) — отдельным решением при деплое (Глава 26): A1 должен
# разрешить IP сервера, иначе каждое SMS вернёт ошибку 5.
# Запуск:  ./scripts/set-a1-secrets.sh [staging] [production]   (по умолчанию — оба)

set -euo pipefail

command -v gh >/dev/null || { echo "Нужен GitHub CLI: brew install gh && gh auth login"; exit 1; }

REPO="${GITHUB_REPO:-$(gh repo view --json nameWithOwner --jq .nameWithOwner)}"
[ $# -gt 0 ] || set -- staging production

read -r -p "Логин A1 (msisdn, только цифры): " a1_user
[[ "$a1_user" =~ ^[0-9]{9,15}$ ]] || { echo "Логин — только цифры, например 375XXXXXXXXX"; exit 1; }
read -r -s -p "API key A1 (ввод скрыт): " a1_key; echo
[ -n "$a1_key" ] || { echo "API-ключ пустой"; exit 1; }
read -r -p "Альфа-имя отправителя (например ETSGOMEL): " a1_sender
[[ "$a1_sender" =~ ^[A-Za-z0-9._-]{1,11}$ ]] || { echo "Альфа-имя — до 11 латинских символов/цифр"; exit 1; }

for env_name in "$@"; do
  printf '%s' "$a1_user" | gh secret set SMS_PROVIDER_USER --repo "$REPO" --env "$env_name"
  printf '%s' "$a1_key" | gh secret set SMS_PROVIDER_API_KEY --repo "$REPO" --env "$env_name"
  gh variable set SMS_SENDER --repo "$REPO" --env "$env_name" --body "$a1_sender"
  echo "→ ${env_name}: SMS_PROVIDER_USER, SMS_PROVIDER_API_KEY (secrets), SMS_SENDER=${a1_sender} (variable)"
done
unset a1_key
