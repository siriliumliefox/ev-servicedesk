#!/usr/bin/env bash
# OWASP ZAP на интеграционном стеке (Глава 25, ADR 0029 п. 7). Запуск — командой после «--»:
#   INTEGRATION_ACCESS_TOKEN_TTL=7200 scripts/integration_stack.sh <образ> -- scripts/zap_scan.sh
# Окружение от стека: API_BASE_URL, E2E_CODE, E2E_JOB_RUNNER, E2E_ZAP_PHONE.
# Проходы:
# - API, активное сканирование по docs/openapi.yaml: без токена (все операции: публичные и отказы
#   401) и от имени client, engineer, admin — операции роли без завершающих сессию
#   (backend/scripts/zap_prepare.py); срок токена стенда — INTEGRATION_ACCESS_TOKEN_TTL;
# - веб-кабинеты (ZAP_WEB=1, по умолчанию): пассивный baseline production-сборки в `vite preview`.
# Отчёты — ZAP_OUT (по умолчанию zap-results/<время UTC>): <проход>.json/.html и summary.md;
# код выхода 1 — есть находки High (backend/scripts/zap_summary.py). Токены — только в окружении
# контейнера ZAP и во временном каталоге 700, в отчёты не пишутся.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ZAP_IMAGE="${ZAP_IMAGE:-ghcr.io/zaproxy/zaproxy@sha256:5ccfff9a411743ab2615136a2edd7416bec9ce41572fa94e935df38c14adb2b6}"  # 2.17.0
OUT="${ZAP_OUT:-$ROOT/zap-results/$(date -u +%Y%m%dT%H%M%SZ)}"
mkdir -p "$OUT"
OUT="$(cd "$OUT" && pwd)"
PRIVATE="$(mktemp -d)"   # токены
SHARE="$(mktemp -d)"     # контракты, правила, отчёты — /zap/wrk контейнера (пользователь zap)
chmod 700 "$PRIVATE"
chmod 777 "$SHARE"
PIDS=()
# shellcheck disable=SC2329  # вызывается из trap
cleanup() {
  for pid in "${PIDS[@]:-}"; do
    if [ -n "$pid" ]; then kill "$pid" 2>/dev/null || true; fi
  done
  rm -rf "$PRIVATE" "$SHARE"
}
trap cleanup EXIT

API_PORT="${API_BASE_URL##*:}"
API_PORT="${API_PORT%%/*}"
# Linux (CI): ZAP в сети хоста. macOS: Docker Desktop — хост как host.docker.internal.
if [ "$(uname -s)" = Darwin ]; then
  ZAP_HOST=host.docker.internal
  NET=()
else
  ZAP_HOST=127.0.0.1
  NET=(--network host)
fi

(cd "$ROOT/backend" && poetry run python scripts/zap_prepare.py --out "$PRIVATE")
cp "$PRIVATE"/openapi-*.yaml "$ROOT/scripts/zap/api-rules.tsv" "$ROOT/scripts/zap/web-rules.tsv" "$SHARE/"
chmod a+r "$SHARE"/*
token() {
  python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))[sys.argv[2]])' "$PRIVATE/tokens.json" "$1"
}

zap() {
  docker run --rm ${NET[@]+"${NET[@]}"} -v "$SHARE:/zap/wrk:rw" "$@"
}

api_scan() {
  local name="$1" token="${2:-}" auth=()
  if [ -n "$token" ]; then
    auth=(-e ZAP_AUTH_HEADER=Authorization -e "ZAP_AUTH_HEADER_VALUE=Bearer $token"
          -e "ZAP_AUTH_HEADER_SITE=$ZAP_HOST")
  fi
  echo "ZAP  API: $name"
  # -I: предупреждения не роняют проход — итог по уровням считает zap_summary.py.
  zap ${auth[@]+"${auth[@]}"} "$ZAP_IMAGE" zap-api-scan.py -t "/zap/wrk/openapi-$name.yaml" -f openapi \
    -O "http://$ZAP_HOST:$API_PORT/v1" -c api-rules.tsv -J "api-$name.json" -r "api-$name.html" \
    -I -T "${ZAP_MAX_MINUTES:-30}" >"$OUT/api-$name.log" 2>&1 || echo "WARN  ZAP API $name: код $?"
}

api_scan anonymous
for role in ${ZAP_ROLES:-client engineer admin}; do api_scan "$role" "$(token "$role")"; done

if [ "${ZAP_WEB:-1}" = 1 ]; then
  for pair in web-engineer:4173 web-admin:4174; do
    app="${pair%%:*}"
    port="${pair##*:}"
    if [ ! -d "$ROOT/$app/dist" ]; then (cd "$ROOT/$app" && npx vite build >/dev/null); fi
    (cd "$ROOT/$app" && EV_API_PROXY="$API_BASE_URL" __VITE_ADDITIONAL_SERVER_ALLOWED_HOSTS="$ZAP_HOST" \
      exec npx vite preview --host 127.0.0.1 --port "$port" --strictPort >"$OUT/$app-preview.log" 2>&1) &
    PIDS+=("$!")
    for _ in $(seq 60); do
      if curl -fsS "http://127.0.0.1:$port/" >/dev/null 2>&1; then break; fi
      sleep 1
    done
    echo "ZAP  веб: $app"
    zap "$ZAP_IMAGE" zap-baseline.py -t "http://$ZAP_HOST:$port/" -c web-rules.tsv \
      -J "web-$app.json" -r "web-$app.html" -I >"$OUT/web-$app.log" 2>&1 || echo "WARN  ZAP веб $app: код $?"
  done
fi

cp "$SHARE"/*.json "$SHARE"/*.html "$OUT/" 2>/dev/null || true
(cd "$ROOT/backend" && poetry run python scripts/zap_summary.py "$OUT")
