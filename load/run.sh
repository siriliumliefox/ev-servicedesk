#!/usr/bin/env bash
# Прогон сценариев k6 на нагрузочном стенде (глава 24, ADR 0028 п. 6, 13, 14). Запускается
# scripts/load_stack.sh после подъёма стека; окружение — от scripts/integration_stack.sh
# (E2E_COMPOSE — префикс docker compose стека, POSTGRES_USER/POSTGRES_DB).
#
# 1. Сид в разовом контейнере из образа-кандидата (backend/scripts/seed_load.py) — один раз.
#    На 7-й минуте каждого сценария — суточные напоминания о ТО (как в 10:00 в production).
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
mkdir -p "$RESULTS" && RESULTS="$(cd "$RESULTS" && pwd)"  # docker -v — только абсолютный путь
SEED_DIR="$(mktemp -d)"
chmod 700 "$SEED_DIR"
STATS_PID=""
REMINDERS_PID=""
# shellcheck disable=SC2329  # вызывается из trap
cleanup() {
  [ -n "$STATS_PID" ] && kill "$STATS_PID" 2>/dev/null || true
  [ -n "$REMINDERS_PID" ] && kill "$REMINDERS_PID" 2>/dev/null || true
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
scenario_no=0
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

  # Суточные напоминания о ТО во время нагрузки — как в 10:00 в production: одна долгая
  # транзакция со ссылками на авто (глава 24: из-за неё обновление пробега ждало до минуты).
  # Дата сдвигается на 30 дней на сценарий — каждый запуск создаёт новые напоминания.
  scenario_no=$((scenario_no + 1))
  reminders_date="$(python3 -c "import datetime,sys; print(datetime.date.today() + datetime.timedelta(days=30 * int(sys.argv[1])))" "$scenario_no")"
  reminders_delay=420
  [ "${LOAD_PROFILE:-full}" = ci ] && reminders_delay=60
  ( sleep "$reminders_delay"
    started=$SECONDS
    "${COMPOSE[@]}" exec -T backend python -m app.workers.maintenance_reminders \
      --date "$reminders_date" >"$out/reminders.log" 2>&1
    echo "duration_seconds=$((SECONDS - started)) date=$reminders_date" >>"$out/reminders.log"
  ) &
  REMINDERS_PID=$!

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
  wait "$REMINDERS_PID" 2>/dev/null || true
  grep -hE "создано|duration_seconds" "$out/reminders.log" 2>/dev/null | sed 's/^/  напоминания о ТО: /' || true

  psql_stack -q --csv -c "
    SELECT calls, round(total_exec_time::numeric, 1) AS total_ms,
           round(mean_exec_time::numeric, 2) AS mean_ms, round(max_exec_time::numeric, 1) AS max_ms,
           rows, regexp_replace(query, '\s+', ' ', 'g') AS query
    FROM pg_stat_statements ORDER BY total_exec_time DESC LIMIT 20" >"$out/pg_top20.csv"
  "${COMPOSE[@]}" logs --no-color --since "$log_since" postgres 2>/dev/null \
    | grep -E 'duration: [0-9.]+ ms' >"$out/pg_slow.log" || true
  # Доставка рассылки (peak, ADR 0028 п. 12) — по БД: последняя доставка или окончательная
  # ошибка от публикации и строки, оставшиеся в очереди. Норматив — 300 с и пустая очередь.
  if [ "$scenario" = peak ]; then
    psql_stack -At -F, -c "
      WITH n AS (SELECT id, created_at FROM notification
                 WHERE type = 'news' AND created_at >= '$log_since' ORDER BY id DESC LIMIT 1)
      SELECT (SELECT count(*) FROM notification_recipient r WHERE r.notification_id = n.id),
             count(d.id), count(d.delivered_at), count(d.failed_at),
             count(*) FILTER (WHERE d.id IS NOT NULL AND d.delivered_at IS NULL AND d.failed_at IS NULL),
             round(extract(epoch FROM max(coalesce(d.delivered_at, d.failed_at)) - n.created_at)),
             round(extract(epoch FROM percentile_disc(0.5) WITHIN GROUP
                   (ORDER BY coalesce(d.delivered_at, d.failed_at)) - n.created_at))
      FROM n LEFT JOIN notification_delivery d ON d.notification_id = n.id
      GROUP BY n.id, n.created_at" >"$out/broadcast.csv" || true
    if ! python3 - "$out" <<'PY'; then status=1; fi
import json, sys
out = sys.argv[1]
row = open(f"{out}/broadcast.csv").read().strip().split(",")
if len(row) < 7 or not row[5]:
    print("FAIL  рассылка: публикации нет или ничего не доставлено")
    sys.exit(1)
keys = ["recipients", "deliveries", "delivered", "failed", "pending", "last_done_s", "median_s"]
b = dict(zip(keys, (int(float(x)) for x in row)))
json.dump(b, open(f"{out}/broadcast.json", "w"))
ok = b["pending"] == 0 and b["last_done_s"] <= 300
print(f"{'PASS' if ok else 'FAIL'}  рассылка: {b['deliveries']} доставок, последняя за "
      f"{b['last_done_s']} с (половина — за {b['median_s']} с), в очереди {b['pending']}")
sys.exit(0 if ok else 1)
PY
  fi
  python3 "$ROOT/load/analyze.py" "$out" || status=1

  if [ "$status" -eq 0 ]; then
    echo "PASS  сценарий $scenario: пороги выполнены"
  else
    echo "FAIL  сценарий $scenario: пороги нарушены (код $status)"; failed=1
  fi
done
exit "$failed"
