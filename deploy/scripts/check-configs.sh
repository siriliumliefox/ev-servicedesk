#!/usr/bin/env bash
# Проверка конфигураций deploy/ без серверов (глава 26, ADR 0030 п. 6) — job infra в ci-gate и локально.
# Рендер шаблонов на значениях обоих окружений, затем в контейнерах закреплённых образов:
# docker compose config, nginx -t (временные сертификаты), promtool check config / check rules /
# test rules, amtool check-config, loki -verify-config, alloy fmt; shellcheck — если установлен.
set -euo pipefail
DEPLOY="$(cd "$(dirname "$0")/.." && pwd)"
work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT
image() { sed -n "s|^ *image: \(.*$1[^ ]*\).*|\1|p" "$DEPLOY/compose.yml" "$DEPLOY/compose.monitoring.yml" | head -1; }
NGINX="$(image nginx:)"
PROM="$(image prom/prometheus:)"
AM="$(image prom/alertmanager:)"
LOKI="$(image grafana/loki:)"
ALLOY="$(image grafana/alloy:)"
fail=0
ZEROS="$(printf '0%.0s' $(seq 1 64))"
check() { local name="$1"; shift; if "$@" > "$work/out" 2>&1; then echo "PASS  $name"; else echo "FAIL  $name"; sed 's/^/      /' "$work/out"; fail=1; fi; }

for env in staging production; do
  out="$work/$env"
  mkdir -p "$out/rendered" "$out/secrets/alertmanager" "$out/textfile"
  for f in app postgres grafana exporter; do : > "$out/secrets/$f.env"; done
  set -a
  # shellcheck disable=SC1090
  . "$DEPLOY/env/$env.env"
  set +a
  export EV_HOME="$out" EV_SECRETS="$out/secrets" EV_TEXTFILE_DIR="$out/textfile" EV_PROJECT="ev-$env" COMPOSE_PROJECT_NAME="ev-$env"
  export BACKEND_IMAGE="ghcr.io/example/backend@sha256:$ZEROS" EV_POSTGRES_IMAGE="ghcr.io/example/postgres@sha256:$ZEROS"
  export EV_TELEGRAM_CHAT_ID=123456789 EV_ALERT_WEBHOOK_URL=http://alert-sink:8080/x EV_DEADMAN_URL_FILE=/etc/alertmanager/secrets/deadman_url EV_PROBE_CA_FILE=/etc/ev-ca/ca.crt
  for t in prometheus/prometheus.yml alertmanager/alertmanager.yml blackbox/blackbox.yml; do
    check "$env: render $t" python3 "$DEPLOY/scripts/render.py" "$DEPLOY/$t.tmpl" "$out/rendered/$(basename "$t")"
  done
  check "$env: docker compose config" docker compose --project-directory "$DEPLOY" -f "$DEPLOY/compose.yml" -f "$DEPLOY/compose.monitoring.yml" config -q
  # nginx -t: шаблоны тем же envsubst официального образа, временные сертификаты на все имена.
  mkdir -p "$out/certs"
  for host in "$EV_API_HOST" "$EV_ENGINEER_HOST" "$EV_ADMIN_HOST"; do
    mkdir -p "$out/certs/live/$host"
    openssl req -x509 -newkey rsa:2048 -nodes -days 1 -subj "/CN=$host" -keyout "$out/certs/live/$host/privkey.pem" \
      -out "$out/certs/live/$host/fullchain.pem" 2>/dev/null
  done
  chmod -R a+rX "$out/certs"
  check "$env: nginx -t" docker run --rm -e NGINX_ENVSUBST_FILTER='^EV_' -e "EV_API_HOST=$EV_API_HOST" \
    -e "EV_ENGINEER_HOST=$EV_ENGINEER_HOST" -e "EV_ADMIN_HOST=$EV_ADMIN_HOST" -e "EV_MEDIA_ORIGIN=$EV_MEDIA_ORIGIN" \
    -e EV_BACKEND_UPSTREAM=127.0.0.1:8000 -v "$DEPLOY/nginx/nginx.conf:/etc/nginx/nginx.conf:ro" \
    -v "$DEPLOY/nginx/templates:/etc/nginx/templates:ro" -v "$DEPLOY/nginx/snippets:/etc/nginx/snippets:ro" \
    -v "$out/certs:/etc/letsencrypt:ro" "$NGINX" sh -c '/docker-entrypoint.d/20-envsubst-on-templates.sh >/dev/null && nginx -t'
  check "$env: promtool check config" docker run --rm --entrypoint promtool -v "$out/rendered:/r:ro" -v "$DEPLOY/prometheus/rules:/etc/prometheus/rules:ro" "$PROM" check config --syntax-only /r/prometheus.yml
  echo dummy > "$out/secrets/alertmanager/telegram_token"
  echo http://x/y > "$out/secrets/alertmanager/deadman_url"
  check "$env: amtool check-config" docker run --rm --entrypoint amtool -v "$out/rendered/alertmanager.yml:/etc/alertmanager/alertmanager.yml:ro" \
    -v "$DEPLOY/alertmanager/templates:/etc/alertmanager/templates:ro" -v "$out/secrets/alertmanager:/etc/alertmanager/secrets:ro" "$AM" check-config /etc/alertmanager/alertmanager.yml
done
check "promtool check rules" docker run --rm --entrypoint promtool -v "$DEPLOY/prometheus:/p:ro" "$PROM" check rules /p/rules/ev.yml
check "promtool test rules" docker run --rm --entrypoint promtool -v "$DEPLOY/prometheus:/p:ro" -w /p/tests "$PROM" test rules ev_test.yml
check "loki -verify-config" docker run --rm -e EV_LOG_RETENTION=720h -v "$DEPLOY/loki:/etc/loki:ro" "$LOKI" -config.file=/etc/loki/loki.yml -config.expand-env=true -verify-config
check "alloy fmt" docker run --rm -v "$DEPLOY/alloy:/a:ro" "$ALLOY" fmt /a/config.alloy
if command -v shellcheck >/dev/null; then
  check "shellcheck" shellcheck -x -P SCRIPTDIR -S warning "$DEPLOY"/scripts/*.sh "$DEPLOY/scripts/ev-ssh" "$DEPLOY/../scripts/infra_stack.sh"
fi
python3 -c "import json,sys; [json.load(open(f)) for f in sys.argv[1:]]" "$DEPLOY"/grafana/dashboards/*.json && echo "PASS  grafana dashboards json" || fail=1
exit "$fail"
