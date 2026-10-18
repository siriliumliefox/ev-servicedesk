#!/usr/bin/env bash
# Ночной облегчённый прогон k6 на staging (глава 26, ADR 0030 п. 20): deploy/load/nightly.js в сети
# окружения напрямую в backend (без nginx и лимитов по IP), итоги — remote write в Prometheus staging.
#
#   nightly-load.sh staging     (ev-ssh: `load staging`; таймер — load-nightly.yml)
#
# Только staging: production нагрузкой не проверяется. Тестовый номер и код — SMS_TEST_PHONES /
# SMS_TEST_CODE из секретов окружения (app.env), в журнал не пишутся.
set -euo pipefail
# shellcheck source=lib.sh
. "$(cd "$(dirname "$0")" && pwd)/lib.sh"

ENV="${1:-}"
[[ "$ENV" == staging ]] || die "ночной прогон — только staging"
DIR="$(release_dir "$ENV" current)" || die "нет текущего выпуска $ENV"
load_release_env "$ENV" "$DIR"
phone="$(sed -n 's/^SMS_TEST_PHONES=//p' "$EV_SECRETS/app.env" | cut -d, -f1)"
code="$(sed -n 's/^SMS_TEST_CODE=//p' "$EV_SECRETS/app.env")"
[[ -n "$phone" && -n "$code" ]] || die "нет SMS_TEST_PHONES / SMS_TEST_CODE в секретах staging"
K6="grafana/k6:2.3.0@sha256:9c2dee7f8ed74d317e4027c06a10f169b625638189de8d4555d0b3486a5aeb34"
log "ночной прогон k6: ${VUS:-20} VU, ${DURATION:-5m}"
docker run --rm --network "ev-${ENV}_app" -v "$DIR/deploy/load:/load:ro" \
  -e BASE_URL=http://backend:8000 -e "EV_PHONE=$phone" -e "EV_CODE=$code" -e "VUS=${VUS:-20}" -e "DURATION=${DURATION:-5m}" \
  -e K6_PROMETHEUS_RW_SERVER_URL=http://prometheus:9090/api/v1/write \
  -e 'K6_PROMETHEUS_RW_TREND_STATS=p(95),p(99)' -e K6_PROMETHEUS_RW_PUSH_INTERVAL=15s \
  "$K6" run --quiet -o experimental-prometheus-rw --tag "testid=nightly-$(date -u +%Y%m%d)" /load/nightly.js
