#!/usr/bin/env bash
# Секреты и переменные окружения GitHub для серверов (глава 26, ADR 0030 п. 17). Запускает ВЛАДЕЛЕЦ в
# своём терминале (не агент): ключи сторонних сервисов вводятся скрыто и сразу уходят в `gh secret set`
# через stdin — в argv, журналы и репозиторий не попадают.
#
#   scripts/set-infra-secrets.sh <staging|production>            — всё по шагам (повтор — ротация)
#   ONLY="S3_ACCESS_KEY S3_SECRET_KEY" scripts/set-infra-secrets.sh staging  — только перечисленные
#
# Генерируются (значения никто не видит): POSTGRES_PASSWORD, POSTGRES_MONITOR_PASSWORD, ключ SSH деплоя
# (публичная часть печатается — её передать в bootstrap.sh). Ключ шифрования бэкапов
# PGBACKREST_CIPHER_PASS генерируется и ОДИН РАЗ показывается — сохраните его в менеджер паролей: секрет
# GitHub прочитать обратно нельзя, без копии восстановление из бэкапа невозможно.
# Вводятся: пароль Grafana, ключи S3 (media и backup), токен бота алертов, ссылка dead-man, ключ хоста (по
# ssh-keyscan с проверкой отпечатка). Переменные (не секреты): SSH_HOST, S3_MEDIA_BUCKET, S3_BACKUP_BUCKET,
# TELEGRAM_CHAT_ID, SMS_PROVIDER. A1 — scripts/set-a1-secrets.sh, FCM — scripts/set-fcm-secret.sh.
set -euo pipefail

ENV="${1:-}"
case "$ENV" in staging|production) ;; *) echo "окружение — staging или production" >&2; exit 2 ;; esac
command -v gh >/dev/null || { echo "нужен GitHub CLI: brew install gh && gh auth login" >&2; exit 1; }
REPO="${GITHUB_REPO:-$(gh repo view --json nameWithOwner --jq .nameWithOwner)}"
want() { [[ -z "${ONLY:-}" || " $ONLY " == *" $1 "* ]]; }
secret() { gh secret set "$1" --env "$ENV" --repo "$REPO" >/dev/null; echo "  ✓ секрет $1"; }
variable() { gh variable set "$1" --env "$ENV" --repo "$REPO" --body "$2" >/dev/null; echo "  ✓ переменная $1=$2"; }
ask_secret() {
  # ask_secret <ИМЯ> <подсказка> — скрытый ввод; пусто — пропуск.
  local value
  read -r -s -p "$2 (пусто — пропустить): " value; echo
  if [[ -n "$value" ]]; then printf '%s' "$value" | secret "$1"; else echo "  – $1 пропущен"; fi
}
ask_var() {
  local value
  read -r -p "$2 [$3]: " value
  variable "$1" "${value:-$3}"
}

echo "Окружение $ENV, репозиторий $REPO"
if want POSTGRES_PASSWORD; then openssl rand -hex 32 | tr -d '\n' | secret POSTGRES_PASSWORD; fi
if want POSTGRES_MONITOR_PASSWORD; then openssl rand -hex 32 | tr -d '\n' | secret POSTGRES_MONITOR_PASSWORD; fi

if want PGBACKREST_CIPHER_PASS; then
  pass="$(openssl rand -base64 48 | tr -d '\n')"
  echo
  echo "Ключ шифрования бэкапов $ENV — сохраните в менеджер паролей СЕЙЧАС (показывается один раз):"
  echo "  $pass"
  read -r -p "Сохранили? (да): " ok
  [[ "$ok" == да ]] || { echo "ключ не записан — повторите, когда будете готовы" >&2; exit 1; }
  printf '%s' "$pass" | secret PGBACKREST_CIPHER_PASS
  unset pass
  printf '\033[2J\033[H'   # очистить экран терминала
fi

if want SSH_DEPLOY_KEY; then
  dir="$(mktemp -d)"
  ssh-keygen -q -t ed25519 -N '' -C "ev-deploy-$ENV" -f "$dir/key"
  secret SSH_DEPLOY_KEY < "$dir/key"
  mkdir -p "$HOME/.ssh"
  cp "$dir/key.pub" "$HOME/.ssh/ev-deploy-$ENV.pub"
  rm -rf "$dir"
  echo "  публичный ключ деплоя → ~/.ssh/ev-deploy-$ENV.pub (передать в bootstrap.sh)"
fi

if want SSH_HOST; then ask_var SSH_HOST "Публичный IPv4 ВМ $ENV" ""; fi
if want SSH_KNOWN_HOSTS; then
  host="$(gh variable get SSH_HOST --env "$ENV" --repo "$REPO" 2>/dev/null || true)"
  if [[ -n "$host" ]]; then
    keys="$(ssh-keyscan -t ed25519 "$host" 2>/dev/null)"
    printf '%s\n' "$keys" | ssh-keygen -lf - 2>/dev/null | sed 's/^/  отпечаток: /'
    read -r -p "Совпадает с отпечатком в консоли ВМ (Timeweb → сервер → консоль: ssh-keygen -lf /etc/ssh/ssh_host_ed25519_key.pub)? (да): " ok
    if [[ "$ok" == да ]]; then printf '%s\n' "$keys" | secret SSH_KNOWN_HOSTS; else echo "  – SSH_KNOWN_HOSTS не записан"; fi
  else
    echo "  – SSH_KNOWN_HOSTS: сначала SSH_HOST"
  fi
fi

if want GRAFANA_ADMIN_PASSWORD; then ask_secret GRAFANA_ADMIN_PASSWORD "Пароль администратора Grafana (запомните — вход через SSH-туннель)"; fi
if want S3_ACCESS_KEY; then ask_secret S3_ACCESS_KEY "S3 Timeweb, ключ доступа бакета media"; fi
if want S3_SECRET_KEY; then ask_secret S3_SECRET_KEY "S3 Timeweb, секретный ключ бакета media"; fi
if want BACKUP_S3_ACCESS_KEY; then ask_secret BACKUP_S3_ACCESS_KEY "S3 Timeweb, ключ доступа бакета backup"; fi
if want BACKUP_S3_SECRET_KEY; then ask_secret BACKUP_S3_SECRET_KEY "S3 Timeweb, секретный ключ бакета backup"; fi
if want S3_MEDIA_BUCKET; then ask_var S3_MEDIA_BUCKET "Имя бакета media" "ev-$ENV-media"; fi
if want S3_BACKUP_BUCKET; then ask_var S3_BACKUP_BUCKET "Имя бакета backup" "ev-$ENV-backup"; fi
if want ALERT_TELEGRAM_BOT_TOKEN; then ask_secret ALERT_TELEGRAM_BOT_TOKEN "Токен бота алертов от @BotFather"; fi
if want TELEGRAM_CHAT_ID; then ask_var TELEGRAM_CHAT_ID "chat_id вашего чата с ботом (scripts/telegram-chat-id.sh)" ""; fi
if want DEADMAN_URL; then ask_secret DEADMAN_URL "Ссылка пинга healthchecks.io (https://hc-ping.com/…)"; fi
if want SMS_PROVIDER && [[ "$ENV" == staging ]]; then
  ask_var SMS_PROVIDER "SMS на staging: fake — до разрешения IP в A1, затем a1" "fake"
fi
echo "Готово. Проверка изоляции: gh workflow run secrets-isolation.yml --ref develop"
