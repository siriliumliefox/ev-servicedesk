#!/usr/bin/env bash
# Сертификаты TLS окружения (глава 26, ADR 0030 п. 18).
#
#   certs.sh placeholder  <env>            — временные самоподписанные (nginx стартует до выпуска)
#   certs.sh local-ca     <env> <каталог>  — подпись УЦ стенда (scripts/infra_stack.sh)
#   certs.sh letsencrypt  <env>            — Let's Encrypt, проверка HTTP-01 через работающий nginx
#
# Let's Encrypt: первый выпуск принимает Subscriber Agreement — решение владельца: запуск только с
# EV_ACME_AGREE_TOS=yes и EV_ACME_EMAIL (docs/runbooks/OWNER_ACTIONS_26.md). Продление — сервис certbot
# (профиль letsencrypt), nginx перечитывает сертификаты раз в 6 ч.
set -euo pipefail
# shellcheck source=lib.sh
. "$(cd "$(dirname "$0")" && pwd)/lib.sh"

[[ $# -ge 2 ]] || { sed -n '2,10p' "$0" >&2; exit 2; }
MODE="$1"
ENV="$2"
check_env_name "$ENV"
DIR="$(release_dir "$ENV" current 2>/dev/null || true)"
if [[ -n "$DIR" ]]; then
  load_release_env "$ENV" "$DIR"
else
  # До первого выпуска — имена из env/<env>.env рядом со скриптом (каталог deploy/ репозитория)
  # и local.env стенда.
  EV_HOME="$(ev_home "$ENV")"
  set -a
  # shellcheck disable=SC1090
  . "$(cd "$(dirname "$0")/.." && pwd)/env/$ENV.env"
  # shellcheck disable=SC1091
  [[ -f "$EV_HOME/local.env" ]] && . "$EV_HOME/local.env"
  set +a
fi
HOSTS=("$EV_API_HOST" "$EV_ENGINEER_HOST" "$EV_ADMIN_HOST")
LIVE="$EV_HOME/certs/live"

issue_with() {
  # issue_with <host> <openssl-аргументы подписи…>
  local host="$1" dir="$LIVE/$1"
  shift
  mkdir -p "$dir"
  openssl req -new -newkey rsa:2048 -nodes -keyout "$dir/privkey.pem" -subj "/CN=$host" \
    -addext "subjectAltName=DNS:$host" -out "$dir/req.csr" 2>/dev/null
  openssl x509 -req -in "$dir/req.csr" -out "$dir/cert.pem" -days 30 -copy_extensions copyall "$@" 2>/dev/null
  cp "$dir/cert.pem" "$dir/fullchain.pem"
  rm -f "$dir/req.csr"
  chmod 0644 "$dir/fullchain.pem" "$dir/cert.pem"
  chmod 0640 "$dir/privkey.pem"
}

case "$MODE" in
  placeholder)
    for host in "${HOSTS[@]}"; do
      [[ -f "$LIVE/$host/fullchain.pem" ]] && continue
      issue_with "$host" -signkey "$LIVE/$host/privkey.pem"
      log "временный сертификат $host"
    done
    ;;
  local-ca)
    ca_dir="${3:?каталог УЦ стенда}"
    for host in "${HOSTS[@]}"; do
      issue_with "$host" -CA "$ca_dir/ca.crt" -CAkey "$ca_dir/ca.key" -CAcreateserial
      log "сертификат УЦ стенда $host"
    done
    ;;
  letsencrypt)
    [[ "${EV_ACME_AGREE_TOS:-}" == yes ]] || die "Let’s Encrypt: Subscriber Agreement принимает владелец — EV_ACME_AGREE_TOS=yes"
    : "${EV_ACME_EMAIL:?EV_ACME_EMAIL — адрес для уведомлений Let’s Encrypt}"
    image="certbot/certbot:v5.8.0@sha256:f70ad0adbb7e117f0fe42a63c553f28ea451edabc0148757b6efcd9735acaa20"
    for host in "${HOSTS[@]}"; do
      if [[ -d "$EV_HOME/certs/renewal" && -f "$EV_HOME/certs/renewal/$host.conf" ]]; then
        log "$host: уже выпущен Let's Encrypt — продлевает certbot"
        continue
      fi
      # Временный сертификат nginx держит в памяти; certbot создаёт live/<host> сам.
      rm -rf "${LIVE:?}/$host"
      docker run --rm -v "$EV_HOME/certs:/etc/letsencrypt" -v "$EV_HOME/acme:/var/www/acme" "$image" \
        certonly --webroot -w /var/www/acme -d "$host" --non-interactive --agree-tos -m "$EV_ACME_EMAIL" --key-type ecdsa
      log "Let's Encrypt: $host"
    done
    [[ -n "$DIR" ]] && dc "$ENV" "$DIR" exec -T nginx nginx -s reload
    ;;
  *) die "режим — placeholder, local-ca или letsencrypt" ;;
esac
