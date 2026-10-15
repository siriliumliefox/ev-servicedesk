#!/usr/bin/env bash
# Прогон сценариев k6 на нагрузочном стенде (глава 24, ADR 0028 п. 6, 13, 14). Запускается
# scripts/load_stack.sh после подъёма стека; окружение — от scripts/integration_stack.sh
# (E2E_COMPOSE — префикс docker compose стека, POSTGRES_USER/POSTGRES_DB).
#
# 1. Сид в разовом контейнере из образа-кандидата (backend/scripts/seed_load.py) — один раз.
# 2. Для каждого сценария: сброс pg_stat_statements, k6 в сети стека (свой X-Forwarded-For у
#    каждого виртуального пользователя), docker stats раз в 5 с, затем топ-20 запросов и журнал
#    медленных запросов. Итог k6 и разбор по минутам (load/analyze.py) — в каталоге результата.
# Код выхода — ненулевой, если хоть один сценарий не прошёл пороги.

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
K6_IMAGE="grafana/k6:2.3.0@sha256:9c2dee7f8ed74d317e4027c06a10f169b625638189de8d4555d0b3486a5aeb34"
: "${E2E_COMPOSE:?запускается из scripts/load_stack.sh}"
read -r -a COMPOSE <<<"$E2E_COMPOSE"
RESULTS="${LOAD_RESULTS:-$ROOT/load/results}"
SEED_DIR="$(mktemp -d)"
chmod 700 "$SEED_DIR"
STATS_PID=""
# shellcheck disable=SC2329  # вызывается из trap
cleanup() {
  [ -n "$STATS_PID" ] && kill "$STATS_PID" 2>/dev/null || true
  rm -rf "$SEED_DIR"  # токены стенда
}
trap cleanup EXIT

psql_stack() {
  "${COMPOSE[@]}" exec -T postgres psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -v ON_ERROR_STOP=1 "$@"
}

backend_container="$("${COMPOSE[@]}" ps -q backend)"
NETWORK="$(docker inspect -f '{{range $k, $v := .NetworkSettings.Networks}}{{$k}}{{end}}' "$backend_container")"

# Сид в разовом контейнере из образа-кандидата: тот же код и окружение (секрет JWT стенда).
seed() {
  "${COMPOSE[@]}" run --rm --no-deps -T -e PYTHONPATH=/app \
    -v "$ROOT/backend/scripts:/app/load_scripts:ro" -v "$SEED_DIR:/out" \
    backend python /app/load_scripts/seed_load.py --out /out/seed.json "$@"
}

psql_stack -q -c "CREATE EXTENSION IF NOT EXISTS pg_stat_statements" >/dev/null
echo "Сид нагрузочных данных (${LOAD_CLIENTS:-10000} клиентов)…"
started=$SECONDS
seed --clients "${LOAD_CLIENTS:-10000}"
echo "PASS  сид за $((SECONDS - started)) с"

failed=0
first=1
for scenario in "$@"; do
  # Refresh-токены прошлого сценария повёрнуты, access истекают через 15 мин — новые сессии.
  [ "$first" -eq 1 ] || seed --tokens-only >/dev/null
  first=0
  script="$ROOT/load/scenarios/$scenario.js"
  [ -f "$script" ] || { echo "FAIL  нет сценария $script"; failed=1; continue; }
  out="$RESULTS/$(date +%Y%m%d-%H%M%S)-$scenario"
  mkdir -p "$out"
  psql_stack -q -c "SELECT pg_stat_statements_reset()" >/dev/null
  log_since="$(date -u +%Y-%m-%dT%H:%M:%SZ)"

  # Ресурсы контейнеров стека раз в 5 с (ADR 0028 п. 14).
  ( while :; do
      docker stats --no-stream --format '{{json .}}' $("${COMPOSE[@]}" ps -q) 2>/dev/null \
        | sed "s/^/{\"t\":$(date +%s),\"s\":/; s/\$/}/" >>"$out/docker_stats.jsonl"
      sleep 5
    done ) &
  STATS_PID=$!

  echo "Сценарий $scenario → ${out#"$ROOT"/}"
  status=0
  docker run --rm --network "$NETWORK" -u "$(id -u):$(id -g)" \
    -v "$ROOT/load:/load:ro" -v "$SEED_DIR:/seed:ro" -v "$out:/out" \
    -e BASE_URL=http://backend:8000 -e SEED=/seed/seed.json -e LOAD_PROFILE="${LOAD_PROFILE:-full}" \
    -e K6_NO_USAGE_REPORT=true \
    "$K6_IMAGE" run --quiet --out json=/out/raw.json.gz "/load/scenarios/$scenario.js" || status=$?
  kill "$STATS_PID" 2>/dev/null || true
  wait "$STATS_PID" 2>/dev/null || true
  STATS_PID=""

  psql_stack -q --csv -c "
    SELECT calls, round(total_exec_time::numeric, 1) AS total_ms,
           round(mean_exec_time::numeric, 2) AS mean_ms, round(max_exec_time::numeric, 1) AS max_ms,
           rows, regexp_replace(query, '\s+', ' ', 'g') AS query
    FROM pg_stat_statements ORDER BY total_exec_time DESC LIMIT 20" >"$out/pg_top20.csv"
  "${COMPOSE[@]}" logs --no-color --since "$log_since" postgres 2>/dev/null \
    | grep -E 'duration: [0-9.]+ ms' >"$out/pg_slow.log" || true
  python3 "$ROOT/load/analyze.py" "$out" || status=1

  if [ "$status" -eq 0 ]; then
    echo "PASS  сценарий $scenario: пороги выполнены"
  else
    echo "FAIL  сценарий $scenario: пороги нарушены (код $status)"; failed=1
  fi
done
exit "$failed"
