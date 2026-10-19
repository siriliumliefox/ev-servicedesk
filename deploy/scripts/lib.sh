# shellcheck shell=bash
# Общее для скриптов deploy/ (глава 26, ADR 0030). Подключается: . "$(dirname "$0")/lib.sh".
# Совместимо с bash 3.2 (Mac стенда) и bash 5 (Ubuntu ВМ): без ассоциативных массивов, sed -i,
# readlink -f, date -d.
#
# Раскладка окружения (EV_HOME, на ВМ — /opt/ev/<окружение>):
#   releases/<sha>/       — выпуск: deploy/ (конфигурации коммита), meta.env, overrides.env
#   current, previous     — symlink на выпуски
#   secrets/              — *.env сервисов и alertmanager/ (0600, из bundle последнего деплоя)
#   web/<app>/<sha>, web/<app>/current — статика кабинетов
#   certs/, acme/         — Let's Encrypt (или УЦ стенда) и каталог проверки HTTP-01

set -euo pipefail

EV_ROOT="${EV_ROOT:-/opt/ev}"
# Хранится выпусков (deploy.sh prune).
# shellcheck disable=SC2034
KEEP_RELEASES=5

log() { printf '%s %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$*" >&2; }
die() { log "ОШИБКА: $*"; exit 1; }

check_env_name() {
  case "${1:-}" in
    staging|production) ;;
    *) die "окружение — staging или production, получено: '${1:-}'" ;;
  esac
}

check_sha() {
  [[ "${1:-}" =~ ^[0-9a-f]{40}$ ]] || die "ожидался полный SHA коммита (40 hex), получено: '${1:-}'"
}

# ev_home <env> — каталог окружения.
ev_home() { printf '%s/%s' "$EV_ROOT" "$1"; }

# release_dir <env> <ref> — каталог выпуска по sha или по имени ссылки (current/previous).
release_dir() {
  local home ref
  home="$(ev_home "$1")"
  ref="$2"
  if [[ "$ref" == current || "$ref" == previous ]]; then
    [[ -L "$home/$ref" ]] || return 1
    (cd "$home/$ref" && pwd -P)
  else
    [[ -d "$home/releases/$ref" ]] || return 1
    printf '%s/releases/%s' "$home" "$ref"
  fi
}

# load_release_env <env> <release-dir> — переменные выпуска в окружение процесса (для render.py и
# проверок).
load_release_env() {
  local env="$1" dir="$2" file
  set -a
  # Порядок: значения окружения, стенд (local.env), переменные GitHub (overrides.env), выпуск (meta.env).
  for file in "$dir/deploy/env/$env.env" "$(ev_home "$env")/local.env" "$dir/overrides.env" "$dir/meta.env"; do
    # shellcheck disable=SC1090
    [[ -f "$file" ]] && . "$file"
  done
  set +a
  export EV_HOME
  EV_HOME="$(ev_home "$env")"
  export EV_SECRETS="$EV_HOME/secrets"
  export COMPOSE_PROJECT_NAME="ev-$env"
  export EV_PROJECT="ev-$env"
  if [[ -f "$EV_SECRETS/alertmanager/deadman_url" ]]; then
    export EV_DEADMAN_URL_FILE=/etc/alertmanager/secrets/deadman_url
  else
    export EV_DEADMAN_URL_FILE=""
  fi
}

# compose_files <release-dir> — аргументы -f для docker compose.
compose_args() {
  local dir="$1" env="$2"
  local args=(-p "ev-$env" --project-directory "$dir/deploy"
    -f "$dir/deploy/compose.yml" -f "$dir/deploy/compose.monitoring.yml")
  if [[ -f "$(ev_home "$env")/compose.local.yml" ]]; then
    args+=(-f "$(ev_home "$env")/compose.local.yml")
  fi
  local file
  for file in "$dir/deploy/env/$env.env" "$(ev_home "$env")/local.env" "$dir/overrides.env" "$dir/meta.env"; do
    [[ -f "$file" ]] && args+=(--env-file "$file")
  done
  printf '%s\n' "${args[@]}"
}

# dc <env> <release-dir> <аргументы docker compose…>
dc() {
  local env="$1" dir="$2"
  shift 2
  local args=()
  local line
  while IFS= read -r line; do args+=("$line"); done < <(compose_args "$dir" "$env")
  docker compose "${args[@]}" "$@"
}

# render_configs <env> <release-dir> — шаблоны *.tmpl → deploy/rendered/.
render_configs() {
  local env="$1" dir="$2"
  load_release_env "$env" "$dir"
  local out="$dir/deploy/rendered"
  mkdir -p "$out"
  python3 "$dir/deploy/scripts/render.py" "$dir/deploy/prometheus/prometheus.yml.tmpl" "$out/prometheus.yml"
  python3 "$dir/deploy/scripts/render.py" "$dir/deploy/alertmanager/alertmanager.yml.tmpl" "$out/alertmanager.yml"
  python3 "$dir/deploy/scripts/render.py" "$dir/deploy/blackbox/blackbox.yml.tmpl" "$out/blackbox.yml"
}

# curl_host <host> <path> [curl-args…] — запрос к nginx этого окружения по имени (как клиент), но на
# локальный адрес: DNS и внешний маршрут не нужны для smoke после выкладки.
curl_host() {
  local host="$1" path="$2"
  shift 2
  local port="${EV_HTTPS_PORT:-443}"
  local ca=()
  [[ -n "${EV_SMOKE_CA_FILE:-}" ]] && ca=(--cacert "$EV_SMOKE_CA_FILE")
  curl -sS --max-time 10 --resolve "$host:$port:127.0.0.1" "${ca[@]+"${ca[@]}"}" "$@" "https://$host:$port$path"
}

# smoke <env> — после выкладки: health через nginx и TLS, 401 без токена, кабинеты с CSP заголовком.
smoke() {
  local status body headers app host
  body="$(curl_host "$EV_API_HOST" /health)" || { log "smoke: /health недоступен"; return 1; }
  [[ "$body" == *'"status":"ok"'* ]] || { log "smoke: /health ответил: $body"; return 1; }
  status="$(curl_host "$EV_API_HOST" /v1/me -o /dev/null -w '%{http_code}')" || return 1
  [[ "$status" == 401 ]] || { log "smoke: /v1/me без токена — $status (ожидался 401)"; return 1; }
  status="$(curl_host "$EV_API_HOST" /metrics -o /dev/null -w '%{http_code}')" || return 1
  [[ "$status" == 404 ]] || { log "smoke: /metrics снаружи — $status (ожидался 404)"; return 1; }
  for app in engineer admin; do
    if [[ "$app" == engineer ]]; then host="$EV_ENGINEER_HOST"; else host="$EV_ADMIN_HOST"; fi
    headers="$(curl_host "$host" / -o /dev/null -D -)" || { log "smoke: кабинет $host недоступен"; return 1; }
    [[ "$headers" == *" 200"* ]] || { log "smoke: кабинет $host — не 200"; return 1; }
    printf '%s' "$headers" | grep -qi "^content-security-policy:.*frame-ancestors 'none'" \
      || { log "smoke: у $host нет CSP с frame-ancestors"; return 1; }
    printf '%s' "$headers" | grep -qi '^strict-transport-security: max-age=31536000' \
      || { log "smoke: у $host нет HSTS"; return 1; }
  done
  log "smoke: PASS (health, 401, /metrics закрыт, кабинеты с CSP и HSTS)"
}

# wait_healthy <env> <release-dir> <сервис> [секунд] — healthy (или running без healthcheck); второй
# перезапуск контейнера — сразу отказ: он падает при старте (fail closed preflight), ждать нечего —
# простой при автооткате короче (учение отката на стенде: 208 с → 20 с).
wait_healthy() {
  local env="$1" dir="$2" service="$3" limit="${4:-180}" waited=0 id state restarts
  while (( waited < limit )); do
    id="$(dc "$env" "$dir" ps -aq "$service" 2>/dev/null | head -1 || true)"
    if [[ -n "$id" ]]; then
      state="$(docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' "$id" 2>/dev/null || true)"
      [[ "$state" == healthy || "$state" == running ]] && return 0
      restarts="$(docker inspect -f '{{.RestartCount}}' "$id" 2>/dev/null || echo 0)"
      if (( restarts >= 2 )); then
        log "$service перезапускается при старте ($restarts раза):"
        docker logs --tail 5 "$id" 2>&1 | sed 's/^/    /' >&2
        return 1
      fi
    fi
    sleep 3
    waited=$((waited + 3))
  done
  log "$service не стал healthy за ${limit} с"
  return 1
}
