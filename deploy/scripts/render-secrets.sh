#!/usr/bin/env bash
# Каталог секретов окружения для bundle деплоя (глава 26, ADR 0030 п. 17).
#
#   render-secrets.sh <env> <каталог>
#
# Значения — переменные окружения с именами секретов GitHub Environment (job cd-staging /
# cd-production передаёт `secrets.*` в env шага) или стенда (scripts/infra_stack.sh). Ничего не
# печатает; нет обязательного — список недостающих ИМЁН и код 1 (fail closed).
# Файлы: app.env (backend и worker'ы), postgres.env (PostgreSQL, pgBackRest), grafana.env,
# exporter.env, alertmanager/telegram_token, alertmanager/deadman_url — формат KEY=значение без кавычек
# (compose env_file format: raw), одна строка на значение.
set -euo pipefail
ENV="${1:?окружение}"
OUT="${2:?каталог}"
case "$ENV" in staging|production) ;; *) echo "окружение — staging или production" >&2; exit 2 ;; esac

missing=()
need() { local name; for name in "$@"; do [[ -n "${!name:-}" ]] || missing+=("$name"); done; }

need JWT_SECRET SMS_CODE_SECRET POSTGRES_PASSWORD POSTGRES_MONITOR_PASSWORD \
  S3_ACCESS_KEY S3_SECRET_KEY BACKUP_S3_ACCESS_KEY BACKUP_S3_SECRET_KEY PGBACKREST_CIPHER_PASS \
  GRAFANA_ADMIN_PASSWORD
[[ "${EV_SMS_PROVIDER:-a1}" == a1 ]] && need SMS_PROVIDER_USER SMS_PROVIDER_API_KEY
[[ "${EV_PUSH_PROVIDER:-fcm}" == fcm ]] && need FCM_SERVICE_ACCOUNT_JSON
if [[ ${#missing[@]} -gt 0 ]]; then
  echo "render-secrets: не заданы секреты окружения $ENV: ${missing[*]}" >&2
  exit 1
fi

line() {
  # line <ИМЯ> <значение> — без переводов строки в значении (одна строка env-файла).
  local value="$2"
  [[ "$value" != *$'\n'* ]] || { echo "render-secrets: $1 содержит перевод строки" >&2; exit 1; }
  printf '%s=%s\n' "$1" "$value"
}
opt() { [[ -n "${!1:-}" ]] && line "$1" "${!1}"; return 0; }

umask 077
mkdir -p "$OUT/alertmanager"
fcm="${FCM_SERVICE_ACCOUNT_JSON:-}"
if [[ -n "$fcm" ]] && command -v jq >/dev/null; then fcm="$(printf '%s' "$fcm" | jq -c .)"; fi
{
  line DATABASE_URL "postgresql+psycopg://ev:${POSTGRES_PASSWORD}@postgres:5432/ev_servicedesk"
  line JWT_SECRET "$JWT_SECRET"
  line SMS_CODE_SECRET "$SMS_CODE_SECRET"
  line S3_ACCESS_KEY "$S3_ACCESS_KEY"
  line S3_SECRET_KEY "$S3_SECRET_KEY"
  opt SMS_PROVIDER_USER
  opt SMS_PROVIDER_API_KEY
  opt SMS_SENDER
  opt SMS_TEST_PHONES
  opt SMS_TEST_CODE
  [[ -n "$fcm" ]] && line FCM_SERVICE_ACCOUNT_JSON "$fcm"
  opt TELEGRAM_BOT_TOKEN
} > "$OUT/app.env"
{
  line POSTGRES_PASSWORD "$POSTGRES_PASSWORD"
  line POSTGRES_MONITOR_PASSWORD "$POSTGRES_MONITOR_PASSWORD"
  line PGBACKREST_REPO1_S3_KEY "$BACKUP_S3_ACCESS_KEY"
  line PGBACKREST_REPO1_S3_KEY_SECRET "$BACKUP_S3_SECRET_KEY"
  line PGBACKREST_REPO1_CIPHER_PASS "$PGBACKREST_CIPHER_PASS"
  # repo2 — внешняя площадка по SFTP (ADR 0030 п. 9), если задана.
  if [[ -n "${PGBACKREST_REPO2_SFTP_HOST:-}" ]]; then
    line PGBACKREST_REPO2_TYPE sftp
    line PGBACKREST_REPO2_PATH /pgbackrest
    line PGBACKREST_REPO2_SFTP_HOST "$PGBACKREST_REPO2_SFTP_HOST"
    line PGBACKREST_REPO2_SFTP_HOST_USER "${PGBACKREST_REPO2_SFTP_HOST_USER:-pgbackrest}"
    line PGBACKREST_REPO2_SFTP_HOST_KEY_HASH_TYPE sha256
    line PGBACKREST_REPO2_SFTP_PRIVATE_KEY_FILE /var/lib/postgresql/.ssh/repo2_key
    line PGBACKREST_REPO2_CIPHER_TYPE aes-256-cbc
    line PGBACKREST_REPO2_CIPHER_PASS "$PGBACKREST_CIPHER_PASS"
    line PGBACKREST_REPO2_RETENTION_FULL 2
  fi
} > "$OUT/postgres.env"
line GF_SECURITY_ADMIN_PASSWORD "$GRAFANA_ADMIN_PASSWORD" > "$OUT/grafana.env"
line DATA_SOURCE_PASS "$POSTGRES_MONITOR_PASSWORD" > "$OUT/exporter.env"
[[ -n "${ALERT_TELEGRAM_BOT_TOKEN:-}" ]] && printf '%s' "$ALERT_TELEGRAM_BOT_TOKEN" > "$OUT/alertmanager/telegram_token"
[[ -n "${DEADMAN_URL:-}" ]] && printf '%s' "$DEADMAN_URL" > "$OUT/alertmanager/deadman_url"
exit 0
