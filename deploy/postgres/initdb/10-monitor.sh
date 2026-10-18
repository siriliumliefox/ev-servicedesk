#!/bin/sh
# Роль экспортёра метрик (глава 26): только pg_monitor, пароль — POSTGRES_MONITOR_PASSWORD.
# Выполняется один раз, на пустом каталоге данных (docker-entrypoint-initdb.d).
set -eu
: "${POSTGRES_MONITOR_PASSWORD:?POSTGRES_MONITOR_PASSWORD не задан}"
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" \
  -v pass="$POSTGRES_MONITOR_PASSWORD" <<'SQL'
CREATE ROLE ev_monitor LOGIN PASSWORD :'pass' IN ROLE pg_monitor;
CREATE EXTENSION IF NOT EXISTS pg_stat_statements;
SQL
