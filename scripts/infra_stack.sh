#!/usr/bin/env bash
# Локальный стенд production-инфраструктуры (глава 26, ADR 0030 п. 23): два «сервера» — staging и
# production — из deploy/ на одном Docker, «провайдер» (MinIO с TLS вместо S3, реестр образов вместо
# ghcr, приёмник алертов вместо Telegram и dead-man) и учения.
#
#   scripts/infra_stack.sh up [staging|production|both]  — провайдер и окружения, выпуск — рабочее дерево
#   scripts/infra_stack.sh release <env> <git-ref|tree>  — собрать и выложить выпуск через deploy.sh
#   scripts/infra_stack.sh drill-rollback   — N → N+1 с миграциями → откат на N → сломанный выпуск → автооткат
#   scripts/infra_stack.sh drill-dr         — пульс записей → «потеря ВМ» staging → новая ВМ → restore.sh: RTO, RPO
#   scripts/infra_stack.sh drill-alerts     — сбои на staging → алерт в приёмнике (и Telegram) за ≤ 5 мин
#   scripts/infra_stack.sh status | down
#
# EV_STAND — каталог стенда (по умолчанию .infra-stand, в .gitignore); EV_DRILL_BASE — выпуск N для
# учений отката (по умолчанию d3257fb — глава 24, миграции до 0015). Telegram — если заданы
# токен бота в EV_STAND/telegram_token (владелец записывает сам, скрытым вводом) и chat_id в
# EV_STAND/telegram_chat_id или EV_TELEGRAM_CHAT_ID. Отчёты учений — EV_STAND/reports.
#
# Отличия от ВМ (в отчёте главы): один Docker на оба окружения; S3 — MinIO; «production» стенда работает
# в режиме staging (A1 и FCM недоступны — фейковые SMS и push); TLS — УЦ стенда; Let's Encrypt не
# используется. Совместимо с bash 3.2 (macOS).
set -euo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd)"
export EV_STAND="${EV_STAND:-$REPO/.infra-stand}"
export EV_ROOT="$EV_STAND/root"
export COPYFILE_DISABLE=1
DEPLOY="$REPO/deploy/scripts"
REGISTRY="localhost:${EV_STAND_REGISTRY_PORT:-15000}"
SINK="http://127.0.0.1:${EV_STAND_SINK_PORT:-18099}"
DRILL_BASE="${EV_DRILL_BASE:-d3257fb}"
# Номер и код для входа клиента на стенде (SMS_TEST_PHONES, ADR 0021 п. 6) — не настоящие.
TEST_PHONE="+375290000926"
TEST_CODE="2626"

log() { printf '%s [stand] %s\n' "$(date +%H:%M:%S)" "$*" >&2; }
die() { log "ОШИБКА: $*"; exit 1; }
report() { mkdir -p "$EV_STAND/reports"; printf '%s\n' "$*" | tee -a "$REPORT"; }

# --- УЦ, провайдер -----------------------------------------------------------------------------

ensure_ca() {
  local ca="$EV_STAND/ca" certs="$EV_STAND/minio-certs"
  mkdir -p "$ca" "$certs/CAs" "$EV_STAND/alerts" "$EV_STAND/reports"
  if [[ ! -f "$ca/ca.crt" ]]; then
    openssl req -x509 -newkey rsa:2048 -nodes -days 365 -subj "/CN=EV-ServiceDesk stand CA" \
      -keyout "$ca/ca.key" -out "$ca/ca.crt" 2>/dev/null
    log "УЦ стенда создан"
  fi
  if [[ ! -f "$certs/public.crt" ]]; then
    openssl req -new -newkey rsa:2048 -nodes -keyout "$certs/private.key" -subj "/CN=s3.stand.test" \
      -addext "subjectAltName=DNS:s3.stand.test" -out "$certs/req.csr" 2>/dev/null
    openssl x509 -req -in "$certs/req.csr" -CA "$ca/ca.crt" -CAkey "$ca/ca.key" -CAcreateserial -days 365 \
      -copy_extensions copyall -out "$certs/public.crt" 2>/dev/null
    rm -f "$certs/req.csr"
    chmod 0644 "$certs/private.key" "$certs/public.crt"
  fi
  cp "$ca/ca.crt" "$certs/CAs/ca.crt"
}

provider_env() {
  local file="$EV_STAND/provider.env"
  if [[ ! -f "$file" ]]; then
    umask 077
    printf 'EV_STAND_S3_KEY=stand%s\nEV_STAND_S3_SECRET=%s\n' "$(openssl rand -hex 4)" "$(openssl rand -hex 24)" > "$file"
    umask 022
  fi
  set -a
  # shellcheck disable=SC1090
  . "$file"
  set +a
}

provider_up() {
  ensure_ca
  provider_env
  docker network inspect ev-edge >/dev/null 2>&1 || docker network create ev-edge >/dev/null
  docker compose -f "$REPO/deploy/stand/provider.yml" up -d --wait minio registry alert-sink >/dev/null
  docker compose -f "$REPO/deploy/stand/provider.yml" run --rm minio-init >/dev/null
  log "провайдер: MinIO (TLS), реестр $REGISTRY, приёмник алертов $SINK"
}

wipe_repo() {
  # wipe_repo <env> — «новая ВМ» с новой БД: репозиторий pgBackRest стенда очищается (на ВМ этого
  # не делает ни один скрипт — backup.sh init сообщает о чужой stanza).
  provider_env
  docker run --rm --network ev-provider -e "SSL_CERT_FILE=/stand-ca/ca.crt" -v "$EV_STAND/minio-certs/CAs:/stand-ca:ro" \
    --entrypoint /bin/sh pgsty/minio:RELEASE.2026-08-04T00-00-00Z@sha256:b6bfe7239bfc83fb90d31612d9704d86039dd714f7904b3f1ad68f211e602372 -ec \
    "mc alias set stand https://s3.stand.test:9000 '$EV_STAND_S3_KEY' '$EV_STAND_S3_SECRET' >/dev/null; mc rm --recursive --force stand/ev-$1-backup/pgbackrest >/dev/null 2>&1 || true"
}

# --- Окружения -------------------------------------------------------------------------------

# chat_id алертов стенда: переменная окружения или файл EV_STAND/telegram_chat_id (не секрет);
# без токена бота (EV_STAND/telegram_token) — пусто: только приёмник стенда.
telegram_chat_id() {
  [[ -s "$EV_STAND/telegram_token" ]] || return 0
  if [[ -n "${EV_TELEGRAM_CHAT_ID:-}" ]]; then echo "$EV_TELEGRAM_CHAT_ID"; return; fi
  [[ -s "$EV_STAND/telegram_chat_id" ]] && tr -d '[:space:]' < "$EV_STAND/telegram_chat_id"
  return 0
}

ports() {
  # ports <env> — «адреса ВМ» на машине стенда.
  if [[ "$1" == staging ]]; then echo "18080 18443 19090 19093 13000"; else echo "28080 28443 29090 29093 23000"; fi
}

hosts_prefix() { if [[ "$1" == staging ]]; then echo "staging."; else echo ""; fi; }

env_setup() {
  local env="$1" home="$EV_ROOT/$1" prefix peer peer_prefix http https prom am graf
  prefix="$(hosts_prefix "$env")"
  if [[ "$env" == staging ]]; then peer=production; else peer=staging; fi
  peer_prefix="$(hosts_prefix "$peer")"
  read -r http https prom am graf <<< "$(ports "$env")"
  mkdir -p "$home" "$EV_ROOT/bin" "$EV_STAND/textfile/$env"
  cp "$REPO/deploy/compose.local.yml" "$home/compose.local.yml"
  cat > "$home/local.env" <<EOF
EV_STAND=$EV_STAND
EV_APP_ENVIRONMENT=staging
COMPOSE_PROFILES=
EV_API_HOST=api.${prefix}etsautogomel.test
EV_ENGINEER_HOST=engineer.${prefix}etsautogomel.test
EV_ADMIN_HOST=admin.${prefix}etsautogomel.test
EV_SELF_HEALTH_URL=https://api.${prefix}etsautogomel.test/health
EV_PEER_HEALTH_URL=https://api.${peer_prefix}etsautogomel.test/health
EV_S3_ENDPOINT=https://s3.stand.test:9000
EV_S3_PUBLIC_ENDPOINT=https://s3.stand.test:9000
EV_MEDIA_ORIGIN=https://s3.stand.test:9000
EV_BACKUP_S3_ENDPOINT=s3.stand.test
EV_SMS_PROVIDER=fake
EV_PUSH_PROVIDER=fake
EV_BIND=127.0.0.1
EV_HTTP_PORT=$http
EV_HTTPS_PORT=$https
EV_PROMETHEUS_PORT=$prom
EV_ALERTMANAGER_PORT=$am
EV_GRAFANA_PORT=$graf
EV_TEXTFILE_DIR=$EV_STAND/textfile/$env
EV_PROBE_CA_FILE=/etc/ev-ca/ca.crt
EV_SMOKE_CA_FILE=$EV_STAND/ca/ca.crt
EV_ALERT_WEBHOOK_URL=http://alert-sink:8080/$env
EV_TELEGRAM_CHAT_ID=$(telegram_chat_id)
EV_RESTORE_NETWORK=ev-provider
EV_RESTORE_EXTRA_ARGS="-e PGBACKREST_REPO1_STORAGE_PORT=9000 -e PGBACKREST_REPO1_STORAGE_CA_FILE=/etc/ev-ca/ca.crt -v $EV_STAND/ca:/etc/ev-ca:ro"
EOF
  local secrets="$EV_STAND/secrets-$env.env"
  if [[ ! -f "$secrets" ]]; then
    umask 077
    {
      for name in JWT_SECRET SMS_CODE_SECRET POSTGRES_PASSWORD POSTGRES_MONITOR_PASSWORD PGBACKREST_CIPHER_PASS GRAFANA_ADMIN_PASSWORD; do
        printf '%s=%s\n' "$name" "$(openssl rand -hex 24)"
      done
      printf 'S3_ACCESS_KEY=%s\nS3_SECRET_KEY=%s\n' "$EV_STAND_S3_KEY" "$EV_STAND_S3_SECRET"
      printf 'BACKUP_S3_ACCESS_KEY=%s\nBACKUP_S3_SECRET_KEY=%s\n' "$EV_STAND_S3_KEY" "$EV_STAND_S3_SECRET"
      printf 'SMS_TEST_PHONES=%s\nSMS_TEST_CODE=%s\n' "$TEST_PHONE" "$TEST_CODE"
      printf 'DEADMAN_URL=http://alert-sink:8080/deadman-%s\n' "$env"
    } > "$secrets"
    umask 022
  fi
  [[ -f "$home/certs/live/api.${prefix}etsautogomel.test/fullchain.pem" ]] || "$DEPLOY/certs.sh" local-ca "$env" "$EV_STAND/ca" >/dev/null
}

# --- Выпуски ---------------------------------------------------------------------------------

# release_sha <ref|tree> — sha выпуска: коммит ref или HEAD для рабочего дерева.
release_sha() { if [[ "$1" == tree ]]; then git -C "$REPO" rev-parse HEAD; else git -C "$REPO" rev-parse "$1^{commit}"; fi; }

# source_dir <ref|tree> <sha> — исходники выпуска: рабочее дерево или git worktree коммита.
source_dir() {
  if [[ "$1" == tree ]]; then echo "$REPO"; return; fi
  local dir="$EV_STAND/src/$2"
  if [[ ! -d "$dir" ]]; then
    git -C "$REPO" worktree add --detach "$dir" "$2" >/dev/null 2>&1 || die "git worktree $2"
  fi
  echo "$dir"
}

push_image() {
  # push_image <локальный тег> <имя в реестре> — печатает ссылку по digest.
  local tag="$1" name="$2" ref
  docker tag "$tag" "$REGISTRY/$name" >/dev/null
  docker push -q "$REGISTRY/$name" >/dev/null
  ref="$(docker inspect -f '{{range .RepoDigests}}{{println .}}{{end}}' "$REGISTRY/$name" | grep "^$REGISTRY/" | head -1)"
  [[ "$ref" == *@sha256:* ]] || die "нет digest у $REGISTRY/$name"
  echo "$ref"
}

build_release() {
  # build_release <ref|tree> — образ backend и статика кабинетов выпуска (кэш по sha).
  local ref="$1" sha src out
  sha="$(release_sha "$ref")"
  src="$(source_dir "$ref" "$sha")"
  out="$EV_STAND/builds/$sha"
  if [[ "$ref" == tree ]]; then rm -rf "$out"; fi
  if [[ ! -f "$out/backend.ref" ]]; then
    mkdir -p "$out"
    log "сборка backend $sha ($ref)"
    docker build -q -t "ev-backend:stand-$sha" "$src/backend" >/dev/null
    push_image "ev-backend:stand-$sha" "ev-backend:stand-$sha" > "$out/backend.ref"
    log "сборка кабинетов $sha"
    if [[ "$ref" != tree ]]; then (cd "$src" && npm ci --no-audit --no-fund --loglevel=error >/dev/null); fi
    (cd "$src" && VITE_API_BASE_URL=/v1 VITE_MEDIA_ORIGIN=https://s3.stand.test:9000 \
      npm run build --workspace web-engineer --workspace web-admin >/dev/null)
    rm -rf "$out/web-engineer" "$out/web-admin"
    cp -R "$src/web-engineer/dist" "$out/web-engineer"
    cp -R "$src/web-admin/dist" "$out/web-admin"
  fi
  if [[ ! -f "$EV_STAND/builds/postgres.ref" || "$ref" == tree ]]; then
    docker build -q -t ev-postgres:stand "$REPO/deploy/postgres" >/dev/null
    push_image ev-postgres:stand ev-postgres:stand > "$EV_STAND/builds/postgres.ref"
  fi
  echo "$sha"
}

# deploy_release <env> <sha> [файл overrides] [sha выпуска вместо sha сборки] — bundle → deploy.sh receive.
deploy_release() {
  local env="$1" sha="$2" overrides="${3:-}" as_sha="${4:-$2}" bundle status=0
  bundle="$EV_STAND/bundle-$env.tar.gz"
  (
    set -a
    # shellcheck disable=SC1090
    . "$EV_STAND/secrets-$env.env"
    set +a
    export EV_SMS_PROVIDER=fake EV_PUSH_PROVIDER=fake
    # Токен бота алертов — из файла стенда, в журнал и аргументы не попадает.
    if [[ -s "$EV_STAND/telegram_token" ]]; then
      ALERT_TELEGRAM_BOT_TOKEN="$(cat "$EV_STAND/telegram_token")"
      export ALERT_TELEGRAM_BOT_TOKEN
    fi
    export EV_SHA="$as_sha" BACKEND_IMAGE EV_POSTGRES_IMAGE
    BACKEND_IMAGE="$(cat "$EV_STAND/builds/$sha/backend.ref")"
    EV_POSTGRES_IMAGE="$(cat "$EV_STAND/builds/postgres.ref")"
    export WEB_ENGINEER_DIST="$EV_STAND/builds/$sha/web-engineer" WEB_ADMIN_DIST="$EV_STAND/builds/$sha/web-admin"
    export EV_OVERRIDES_FILE="$overrides"
    "$DEPLOY/make-bundle.sh" "$env" "$bundle"
  )
  "$DEPLOY/deploy.sh" receive "$env" < "$bundle" || status=$?
  rm -f "$bundle"
  return "$status"
}

dc_env() {
  # dc_env <env> <аргументы compose…> — compose текущего выпуска окружения.
  local env="$1"
  shift
  # shellcheck source=../deploy/scripts/lib.sh
  ( . "$DEPLOY/lib.sh"; dir="$(release_dir "$env" current)"; load_release_env "$env" "$dir"; dc "$env" "$dir" "$@" )
}

psql_env() { dc_env "$1" exec -T postgres psql -U ev -d ev_servicedesk -v ON_ERROR_STOP=1 -Atc "$2"; }

up() {
  local which="${1:-both}" sha env
  provider_up
  sha="$(build_release tree)"
  for env in staging production; do
    [[ "$which" == both || "$which" == "$env" ]] || continue
    env_setup "$env"
    deploy_release "$env" "$sha"
  done
  status
}

status() {
  local env
  for env in staging production; do
    [[ -f "$EV_ROOT/$env/state" ]] || continue
    printf '%s: %s\n' "$env" "$(tr '\n' ' ' < "$EV_ROOT/$env/state")"
  done
  printf 'Grafana: staging http://127.0.0.1:13000, production http://127.0.0.1:23000 (admin, пароль — %s)\n' "$EV_STAND/secrets-*.env"
}

down() {
  local env
  for env in staging production; do
    if [[ -L "$EV_ROOT/$env/current" ]]; then dc_env "$env" down -v --remove-orphans >/dev/null 2>&1 || true; fi
  done
  docker compose -f "$REPO/deploy/stand/provider.yml" down -v >/dev/null 2>&1 || true
  docker network rm ev-edge >/dev/null 2>&1 || true
  local dir
  for dir in "$EV_STAND"/src/*; do [[ -d "$dir" ]] && git -C "$REPO" worktree remove --force "$dir" >/dev/null 2>&1 || true; done
  rm -rf "$EV_STAND"
  log "стенд удалён"
}

# --- Учения ------------------------------------------------------------------------------------

client_token() {
  # Вход клиента тестовым номером (SMS не отправляется) — access-токен для запросов с данными. Токен
  # кэшируется (живёт 15 мин): лимиты N-06 — 5 кодов в час на номер и 30 на IP — работают и на стенде.
  local env="$1" https host cache="$EV_STAND/token-$1" token body
  read -r _ https _ _ _ <<< "$(ports "$env")"
  host="api.$(hosts_prefix "$env")etsautogomel.test"
  if [[ -f "$cache" ]]; then
    token="$(cat "$cache")"
    [[ "$(api "$env" /v1/me "$token")" == 200 ]] && { echo "$token"; return 0; }
  fi
  curl -sS --cacert "$EV_STAND/ca/ca.crt" --resolve "$host:$https:127.0.0.1" -X POST \
    -H 'Content-Type: application/json' -d "{\"phone\":\"$TEST_PHONE\"}" "https://$host:$https/v1/auth/phone/request-code" >/dev/null
  body="$(curl -sS --cacert "$EV_STAND/ca/ca.crt" --resolve "$host:$https:127.0.0.1" -X POST \
    -H 'Content-Type: application/json' \
    -d "{\"phone\":\"$TEST_PHONE\",\"code\":\"$TEST_CODE\",\"pd_policy_version\":\"2026-10\"}" \
    "https://$host:$https/v1/auth/phone/verify-code")"
  token="$(printf '%s' "$body" | python3 -c 'import json,sys; print(json.load(sys.stdin).get("access_token", ""))')"
  [[ -n "$token" ]] || die "вход клиента на $env не удался: $(printf '%s' "$body" | head -c 200)"
  (umask 077 && printf '%s' "$token" > "$cache")
  echo "$token"
}

api() {
  # api <env> <путь> [токен] — код ответа HTTP через nginx окружения.
  local env="$1" path="$2" token="${3:-}" https host
  read -r _ https _ _ _ <<< "$(ports "$env")"
  host="api.$(hosts_prefix "$env")etsautogomel.test"
  curl -sS -o /dev/null -w '%{http_code}' --max-time 10 --cacert "$EV_STAND/ca/ca.crt" --resolve "$host:$https:127.0.0.1" \
    ${token:+-H "Authorization: Bearer $token"} "https://$host:$https$path" || echo 000
}

drill_rollback() {
  REPORT="$EV_STAND/reports/drill-rollback-$(date +%Y%m%d-%H%M%S).md"
  local env=staging base head t0 t1 broken overrides
  provider_up
  report "# Учение отката (staging стенда) — $(date -u +%Y-%m-%dT%H:%M:%SZ)"
  base="$(build_release "$DRILL_BASE")"
  head="$(build_release tree)"
  report "- выпуск N = $base ($DRILL_BASE), N+1 = $head (рабочее дерево)"
  # Чистое окружение: «новая ВМ» с выпуском N.
  if [[ -L "$EV_ROOT/$env/current" ]]; then dc_env "$env" down -v --remove-orphans >/dev/null 2>&1 || true; fi
  rm -rf "${EV_ROOT:?}/$env"
  wipe_repo "$env"
  env_setup "$env"
  t0=$(date +%s); deploy_release "$env" "$base"; t1=$(date +%s)
  report "- N включён за $((t1 - t0)) с; схема: $(psql_env "$env" 'select version_num from alembic_version')"
  local token
  token="$(client_token "$env")"
  report "- клиент вошёл, /v1/vehicles = $(api "$env" /v1/vehicles "$token")"
  t0=$(date +%s); deploy_release "$env" "$head"; t1=$(date +%s)
  report "- N+1 включён за $((t1 - t0)) с (миграции, up, smoke); схема: $(psql_env "$env" 'select version_num from alembic_version')"
  t0=$(date +%s); EV_ROOT="$EV_ROOT" "$DEPLOY/deploy.sh" rollback "$env"; t1=$(date +%s)
  report "- откат N+1 → N за $((t1 - t0)) с без downgrade; схема осталась $(psql_env "$env" 'select version_num from alembic_version'), образ N работает: /v1/vehicles = $(api "$env" /v1/vehicles "$token") (сессия клиента сохранилась)"
  t0=$(date +%s); deploy_release "$env" "$head"; t1=$(date +%s)
  report "- снова N+1 за $((t1 - t0)) с"
  # Сломанный выпуск 1: ошибка настроек, которую видят миграции (неизвестный SMS-провайдер) — выпуск
  # не включается, работающий не тронут.
  broken="$(printf 'b%.0s' $(seq 1 40))"
  overrides="$EV_STAND/broken-overrides.env"
  printf 'EV_SMS_PROVIDER=broken-provider\n' > "$overrides"
  t0=$(date +%s)
  if deploy_release "$env" "$head" "$overrides" "$broken"; then die "выпуск с неверными настройками включился"; fi
  t1=$(date +%s)
  [[ "$(basename "$(cd "$EV_ROOT/$env/current" && pwd -P)")" == "$head" ]] || die "current сменился"
  report "- сломанный выпуск 1 (неверный SMS_PROVIDER): миграции отказали, выпуск не включён за $((t1 - t0)) с, работает N+1, /health = $(api "$env" /health)"
  # Сломанный выпуск 2: ошибка видна только при старте API (несуществующий бакет S3 — fail closed
  # preflight): переключение, health не проходит, автооткат на N+1.
  broken="$(printf 'c%.0s' $(seq 1 40))"
  printf 'EV_S3_MEDIA_BUCKET=ev-staging-media-missing\n' > "$overrides"
  t0=$(date +%s)
  if deploy_release "$env" "$head" "$overrides" "$broken"; then die "выпуск без бакета включился"; fi
  t1=$(date +%s)
  [[ "$(basename "$(cd "$EV_ROOT/$env/current" && pwd -P)")" == "$head" ]] || die "после автоотката current ≠ N+1"
  report "- сломанный выпуск 2 (нет бакета S3): переключён, health не прошёл, **автооткат** на N+1 — всего $((t1 - t0)) с; /health = $(api "$env" /health), /v1/vehicles = $(api "$env" /v1/vehicles "$token")"
  report "- итог: PASS"
  log "отчёт: $REPORT"
}

drill_dr() {
  REPORT="$EV_STAND/reports/drill-dr-$(date +%Y%m%d-%H%M%S).md"
  local env=staging sha pulse t_disaster t_up last rpo rto counts_before counts_after
  provider_up
  sha="$(build_release tree)"
  [[ -L "$EV_ROOT/$env/current" ]] || { env_setup "$env"; deploy_release "$env" "$sha"; }
  sha="$(basename "$(cd "$EV_ROOT/$env/current" && pwd -P)")"
  report "# Учебное восстановление (DR drill, staging стенда) — $(date -u +%Y-%m-%dT%H:%M:%SZ)"
  report "- выпуск $sha; репозиторий pgBackRest — S3 стенда (MinIO), шифрование aes-256-cbc"
  local token
  token="$(client_token "$env")"
  api "$env" /v1/vehicles "$token" >/dev/null
  # Пульс: запись раз в 2 с — по последней восстановленной считается RPO.
  psql_env "$env" "create schema if not exists ops; create table if not exists ops.dr_pulse(ts timestamptz primary key default clock_timestamp())" >/dev/null
  EV_ROOT="$EV_ROOT" "$DEPLOY/backup.sh" full "$env"
  report "- полный бэкап выполнен; $(EV_ROOT="$EV_ROOT" "$DEPLOY/backup.sh" info "$env" 2>/dev/null | grep -E 'full backup|wal archive min/max' | head -2 | tr -s ' ' | tr '\n' ';')"
  ( while :; do psql_env "$env" "insert into ops.dr_pulse default values" >/dev/null 2>&1 || true; sleep 2; done ) &
  pulse=$!
  sleep 90
  counts_before="$(psql_env "$env" "select (select count(*) from app_user)||'/'||(select count(*) from vehicle)||'/'||(select count(*) from ops.dr_pulse)")"
  t_disaster=$(date +%s)
  kill "$pulse" 2>/dev/null || true
  wait "$pulse" 2>/dev/null || true
  # Авария, а не остановка: SIGKILL — PostgreSQL не успевает дописать и отправить текущий сегмент WAL
  # (штатная остановка архивирует его — RPO вышел бы нечестно малым).
  dc_env "$env" kill >/dev/null 2>&1 || true
  report "- $(date -u -r "$t_disaster" +%H:%M:%SZ 2>/dev/null || date -u -d "@$t_disaster" +%H:%M:%SZ): «потеря ВМ» — процессы убиты (SIGKILL), контейнеры, тома и каталог окружения удалены (строк app_user/vehicle/pulse: $counts_before)"
  dc_env "$env" down -v --remove-orphans >/dev/null 2>&1
  rm -rf "${EV_ROOT:?}/$env"
  # «Новая ВМ»: каталог окружения, выпуск без включения, восстановление.
  env_setup "$env"
  (
    set -a
    # shellcheck disable=SC1090
    . "$EV_STAND/secrets-$env.env"
    set +a
    export EV_SMS_PROVIDER=fake EV_PUSH_PROVIDER=fake EV_SHA="$sha"
    BACKEND_IMAGE="$(cat "$EV_STAND/builds/$sha/backend.ref" 2>/dev/null || cat "$EV_STAND/builds/$(git -C "$REPO" rev-parse HEAD)/backend.ref")"
    EV_POSTGRES_IMAGE="$(cat "$EV_STAND/builds/postgres.ref")"
    export BACKEND_IMAGE EV_POSTGRES_IMAGE
    export WEB_ENGINEER_DIST="$EV_STAND/builds/$sha/web-engineer" WEB_ADMIN_DIST="$EV_STAND/builds/$sha/web-admin"
    "$DEPLOY/make-bundle.sh" "$env" "$EV_STAND/bundle-dr.tar.gz"
  )
  EV_RECEIVE_ONLY=1 "$DEPLOY/deploy.sh" receive "$env" < "$EV_STAND/bundle-dr.tar.gz"
  rm -f "$EV_STAND/bundle-dr.tar.gz"
  "$DEPLOY/restore.sh" "$env" "$sha"
  t_up=$(date +%s)
  last="$(psql_env "$env" "select extract(epoch from max(ts))::bigint from ops.dr_pulse")"
  rpo=$((t_disaster - last))
  rto=$((t_up - t_disaster))
  counts_after="$(psql_env "$env" "select (select count(*) from app_user)||'/'||(select count(*) from vehicle)||'/'||(select count(*) from ops.dr_pulse)")"
  report "- восстановлено: строк $counts_after; последняя запись пульса за ${rpo} с до аварии → **RPO ${rpo} с** (цель ≤ 300)"
  report "- **RTO ${rto} с** от аварии до PASS smoke (цель ≤ 7200); вход клиента той же сессией: /v1/vehicles = $(api "$env" /v1/vehicles "$token")"
  report "- аудит целостности: $(dc_env "$env" exec -T backend python -m app.tools.integrity 2>&1 | tail -1)"
  psql_env "$env" "drop schema ops cascade" >/dev/null
  if (( rpo <= 300 && rto <= 7200 )); then report "- итог: PASS"; else report "- итог: FAIL"; fi
  log "отчёт: $REPORT"
}

wait_alert() {
  # wait_alert <env> <alertname> <с какого времени> <лимит, с> — секунды до первого firing в приёмнике.
  local env="$1" name="$2" since="$3" limit="$4" now
  while :; do
    now=$(date +%s)
    if curl -fsS "$SINK/alerts" | python3 -c '
import json, sys
env, name, since = sys.argv[1], sys.argv[2], float(sys.argv[3])
for line in sys.stdin:
    e = json.loads(line)
    if e["channel"] != env or e["received_at"] < since:
        continue
    for a in e["payload"].get("alerts", []):
        if a["status"] == "firing" and a["labels"].get("alertname") == name:
            print(int(e["received_at"] - since)); sys.exit(0)
sys.exit(1)' "$env" "$name" "$since"; then return 0; fi
    (( now - since < limit )) || { echo "нет за ${limit} с"; return 1; }
    sleep 5
  done
}

drill_alerts() {
  REPORT="$EV_STAND/reports/drill-alerts-$(date +%Y%m%d-%H%M%S).md"
  local env=staging t0 took token traffic
  provider_up
  [[ -L "$EV_ROOT/$env/current" && -L "$EV_ROOT/production/current" ]] || up both >/dev/null
  report "# Тест алертов (стенд) — $(date -u +%Y-%m-%dT%H:%M:%SZ)"
  report "- канал: приёмник стенда${EV_TELEGRAM_CHAT_ID:+ и Telegram (chat $EV_TELEGRAM_CHAT_ID)}; цель critical — ≤ 300 с от сбоя до уведомления"
  report ""
  report "| Сбой | Алерт | Секунд до уведомления | Итог |"
  report "|---|---|---|---|"
  sleep 60   # Prometheus набирает данные после выкладки

  t0=$(date +%s); dc_env "$env" stop backend >/dev/null
  took="$(wait_alert "$env" ServiceDown "$t0" 420 || true)"
  report "| остановлен backend | ServiceDown | $took | $([[ "$took" =~ ^[0-9]+$ ]] && (( took <= 300 )) && echo PASS || echo FAIL) |"
  dc_env "$env" start backend >/dev/null; sleep 60

  token="$(client_token "$env")"
  ( while :; do api "$env" /v1/vehicles "$token" >/dev/null; sleep 0.5; done ) &
  traffic=$!
  sleep 60
  t0=$(date +%s); dc_env "$env" stop postgres >/dev/null
  took="$(wait_alert "$env" HighErrorRate "$t0" 420 || true)"
  report "| остановлен PostgreSQL под нагрузкой 2 rps | HighErrorRate | $took | $([[ "$took" =~ ^[0-9]+$ ]] && (( took <= 300 )) && echo PASS || echo FAIL) |"
  took="$(wait_alert "$env" PostgresDown "$t0" 60 || true)"
  report "| (тот же сбой) | PostgresDown | $took | $([[ "$took" =~ ^[0-9]+$ ]] && (( took <= 300 )) && echo PASS || echo FAIL) |"
  dc_env "$env" start postgres >/dev/null
  kill "$traffic" 2>/dev/null || true; wait "$traffic" 2>/dev/null || true
  sleep 60

  t0=$(date +%s); dc_env "$env" stop notifications-worker >/dev/null
  took="$(wait_alert "$env" WorkerDown "$t0" 420 || true)"
  report "| остановлен notifications-worker | WorkerDown | $took | $([[ "$took" =~ ^[0-9]+$ ]] && (( took <= 300 )) && echo PASS || echo FAIL) |"
  dc_env "$env" start notifications-worker >/dev/null

  t0=$(date +%s); dc_env production stop nginx >/dev/null
  took="$(wait_alert "$env" PeerDown "$t0" 420 || true)"
  report "| недоступен production (nginx) — видно с staging | PeerDown | $took | $([[ "$took" =~ ^[0-9]+$ ]] && (( took <= 300 )) && echo PASS || echo FAIL) |"
  dc_env production start nginx >/dev/null

  # Dead-man: Watchdog приходит раз в минуту; без него внешний сервис пишет владельцу.
  local pings
  pings="$(curl -fsS "$SINK/alerts" | grep -c "\"channel\": \"deadman-$env\"" || true)"
  report "| (постоянно) | Watchdog → dead-man | сигналов от staging: $pings | $([[ "$pings" -gt 0 ]] && echo PASS || echo FAIL) |"
  log "отчёт: $REPORT"
}

main() {
  case "${1:-}" in
    up) up "${2:-both}" ;;
    release) [[ $# -eq 3 ]] || die "release <env> <git-ref|tree>"; provider_up; env_setup "$2"; deploy_release "$2" "$(build_release "$3")" ;;
    drill-rollback) drill_rollback ;;
    drill-dr) drill_dr ;;
    drill-alerts) drill_alerts ;;
    status) status ;;
    down) down ;;
    *) sed -n '2,20p' "$0" >&2; exit 2 ;;
  esac
}

main "$@"
