#!/usr/bin/env bash
# Генерирует и записывает JWT_SECRET и SMS_CODE_SECRET (HMAC SMS-кодов, Глава 10,
# ADR 0013) в окружения staging и production (Глава 4, ADR 0008). Значение нигде не печатается и не попадает в argv:
# openssl → переменная оболочки → stdin `gh secret set`.
#
# Для проверки изоляции (workflow secrets-isolation.yml) в переменные
# репозитория пишется отпечаток JWT_SECRET_FP_<ENV> — первые 16 hex
# SHA-256 от значения. По нему секрет не восстановить (256 бит энтропии),
# но можно убедиться, что job видит секрет именно своего окружения.
#
# Повторный запуск РОТИРУЕТ секреты (старые токены станут недействительны).
# SECRETS выбирает, какие секреты генерировать (по умолчанию оба), например добавить
# SMS_CODE_SECRET, не трогая JWT_SECRET:
#   SECRETS=SMS_CODE_SECRET ./scripts/set-environment-secrets.sh
# Запуск:  ./scripts/set-environment-secrets.sh [staging] [production]

set -euo pipefail

command -v gh >/dev/null || { echo "Нужен GitHub CLI: brew install gh && gh auth login"; exit 1; }

REPO="${GITHUB_REPO:-$(gh repo view --json nameWithOwner --jq .nameWithOwner)}"
[ $# -gt 0 ] || set -- staging production

SECRETS="${SECRETS:-JWT_SECRET SMS_CODE_SECRET}"
for name in $SECRETS; do
  case "$name" in JWT_SECRET|SMS_CODE_SECRET) ;; *) echo "Неизвестный секрет: $name"; exit 1 ;; esac
done

for env_name in "$@"; do
  for name in $SECRETS; do
    secret=$(openssl rand -hex 32)
    printf '%s' "$secret" | gh secret set "$name" --repo "$REPO" --env "$env_name"
    if [ "$name" = JWT_SECRET ]; then
      fp=$(printf '%s' "$secret" | shasum -a 256 | cut -c1-16)
      var="JWT_SECRET_FP_$(tr '[:lower:]' '[:upper:]' <<<"$env_name")"
      gh variable set "$var" --repo "$REPO" --body "$fp"
      echo "→ ${env_name}: JWT_SECRET записан, ${var}=${fp}"
    else
      echo "→ ${env_name}: ${name} записан"
    fi
    unset secret
  done
done
