#!/usr/bin/env bash
# OWASP ZAP по адресам окружения через nginx и TLS (глава 26, ADR 0030 п. 20; ADR 0029 п. 7).
#
#   ZAP_TARGET=stand|staging|production scripts/zap_server.sh
#
# В отличие от scripts/zap_scan.sh (стенд из образа, uvicorn и vite preview напрямую) — тот же путь, что у
# клиента: имена, TLS, HSTS, CSP заголовком и прокси /v1 nginx.
# - stand: staging локального стенда (scripts/infra_stack.sh) — ZAP в сети ev-edge стенда, где nginx
#   отвечает по своим именам на 443 (как в интернете).
# - staging: https://api.staging.etsautogomel.by и кабинеты — активный скан API по docs/openapi.yaml без
#   токена и от имени клиента (ZAP_CLIENT_TOKEN, необязательно) + пассивный baseline кабинетов.
# - production: только пассивный baseline (ADR 0030 п. 20 — активный скан production не проводится).
# Отчёты — ZAP_OUT (по умолчанию zap-results/server-<время UTC>), summary.md и код выхода 1 при High
# (backend/scripts/zap_summary.py). Токен — только в окружении контейнера ZAP.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
TARGET="${ZAP_TARGET:?stand, staging или production}"
ZAP_IMAGE="${ZAP_IMAGE:-ghcr.io/zaproxy/zaproxy@sha256:5ccfff9a411743ab2615136a2edd7416bec9ce41572fa94e935df38c14adb2b6}"  # 2.17.0
OUT="${ZAP_OUT:-$ROOT/zap-results/server-$(date -u +%Y%m%dT%H%M%SZ)}"
mkdir -p "$OUT"
SHARE="$(mktemp -d)"
chmod 777 "$SHARE"
trap 'rm -rf "$SHARE"' EXIT
cp "$ROOT/docs/openapi.yaml" "$ROOT/scripts/zap/api-rules.tsv" "$ROOT/scripts/zap/web-rules.tsv" "$SHARE/"
chmod a+r "$SHARE"/*

env_name=staging
[[ "$TARGET" == production ]] && env_name=production
set -a
# shellcheck disable=SC1090
. "$ROOT/deploy/env/$env_name.env"
set +a
port=""
hosts=()
if [[ "$TARGET" == stand ]]; then
  EV_API_HOST=api.staging.etsautogomel.test
  EV_ENGINEER_HOST=engineer.staging.etsautogomel.test
  EV_ADMIN_HOST=admin.staging.etsautogomel.test
  hosts=(--network ev-edge)
fi
api="https://$EV_API_HOST$port"

zap() { docker run --rm ${hosts[@]+"${hosts[@]}"} -v "$SHARE:/zap/wrk:rw" "$@"; }

if [[ "$TARGET" != production ]]; then
  # Сначала клиент: access-токен живёт 15 мин (ADR 0013), проход без токена — после.
  if [[ -n "${ZAP_CLIENT_TOKEN:-}" ]]; then
    echo "ZAP  API клиента"
    zap -e ZAP_AUTH_HEADER=Authorization -e "ZAP_AUTH_HEADER_VALUE=Bearer $ZAP_CLIENT_TOKEN" -e "ZAP_AUTH_HEADER_SITE=$EV_API_HOST" \
      "$ZAP_IMAGE" zap-api-scan.py -t /zap/wrk/openapi.yaml -f openapi -O "$api/v1" -c api-rules.tsv \
      -J api-client.json -r api-client.html -I -T "${ZAP_MAX_MINUTES:-20}" >"$OUT/api-client.log" 2>&1 \
      || echo "WARN  ZAP API клиента: код $?"
  fi
  echo "ZAP  API без токена: $api/v1"
  zap "$ZAP_IMAGE" zap-api-scan.py -t /zap/wrk/openapi.yaml -f openapi -O "$api/v1" -c api-rules.tsv \
    -J api-anonymous.json -r api-anonymous.html -I -T "${ZAP_MAX_MINUTES:-20}" >"$OUT/api-anonymous.log" 2>&1 \
    || echo "WARN  ZAP API без токена: код $?"
else
  echo "ZAP  API, пассивно: $api/health"
  zap "$ZAP_IMAGE" zap-baseline.py -t "$api/health" -c api-rules.tsv -J api-baseline.json -r api-baseline.html -I \
    >"$OUT/api-baseline.log" 2>&1 || echo "WARN  ZAP API baseline: код $?"
fi
for host in "$EV_ENGINEER_HOST" "$EV_ADMIN_HOST"; do
  name="${host%%.*}"
  echo "ZAP  кабинет $name: https://$host$port/"
  zap "$ZAP_IMAGE" zap-baseline.py -t "https://$host$port/" -c web-rules.tsv -J "web-$name.json" -r "web-$name.html" -I \
    >"$OUT/web-$name.log" 2>&1 || echo "WARN  ZAP кабинет $name: код $?"
done

cp "$SHARE"/*.json "$SHARE"/*.html "$OUT/" 2>/dev/null || true
python3 "$ROOT/backend/scripts/zap_summary.py" "$OUT"
