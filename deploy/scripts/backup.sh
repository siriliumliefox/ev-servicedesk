#!/usr/bin/env bash
# Бэкапы PostgreSQL через pgBackRest (глава 26, ADR 0030 п. 9). Таймеры systemd (bootstrap.sh):
#
#   backup.sh init          <env>  — stanza и первый полный бэкап, если их ещё нет (deploy.sh)
#   backup.sh full|diff     <env>  — полный (вс 03:00) / разностный (ежедневно 03:00) во все репозитории
#   backup.sh verify        <env>  — check + verify репозиториев (еженедельно)
#   backup.sh restore-check <env>  — восстановление в изолированный контейнер (ежемесячно): аудит
#                                   целостности и счётчики строк
#   backup.sh info          <env>
#
# Итог — метрики textfile-collector node_exporter (EV_TEXTFILE_DIR/ev_backup.prom):
# ev_backup_last_success_timestamp_seconds{type} и ev_backup_last_failure_timestamp_seconds{type} —
# алерты BackupStale, FullBackupStale, BackupVerifyFailed.
set -euo pipefail
# shellcheck source=lib.sh
. "$(cd "$(dirname "$0")" && pwd)/lib.sh"

repos() {
  # repo2 (SFTP, внешняя площадка) — если задан хост в секретах PostgreSQL.
  if grep -q '^PGBACKREST_REPO2_SFTP_HOST=.' "$EV_SECRETS/postgres.env" 2>/dev/null; then echo "1 2"; else echo 1; fi
}

pgbr() { dc "$ENV" "$DIR" exec -T -u postgres postgres pgbackrest --stanza=ev "$@"; }

record() {
  # record <type> <success|failure> — атомарная запись строки в файл textfile-collector.
  local type="$1" outcome="$2" file="$EV_TEXTFILE_DIR/ev_backup.prom" tmp now metric
  now="$(date +%s)"
  metric="ev_backup_last_${outcome}_timestamp_seconds"
  mkdir -p "$EV_TEXTFILE_DIR"
  tmp="$(mktemp "$EV_TEXTFILE_DIR/.ev_backup.XXXXXX")"
  {
    echo "# HELP ev_backup_last_success_timestamp_seconds Время последнего успешного запуска backup.sh по типу"
    echo "# TYPE ev_backup_last_success_timestamp_seconds gauge"
    echo "# HELP ev_backup_last_failure_timestamp_seconds Время последнего неуспешного запуска backup.sh по типу"
    echo "# TYPE ev_backup_last_failure_timestamp_seconds gauge"
    [[ -f "$file" ]] && grep '^ev_backup_' "$file" | grep -v "^${metric}{type=\"${type}\"}" || true
    echo "${metric}{type=\"${type}\"} ${now}"
  } > "$tmp"
  chmod 0644 "$tmp"
  mv "$tmp" "$file"
}

run() {
  # run <type> <команда…> — выполнить и записать итог.
  local type="$1"
  shift
  if "$@"; then
    record "$type" success
    log "PASS backup $type"
  else
    record "$type" failure
    die "backup $type не выполнен"
  fi
}

backup_all() {
  local type="$1" repo
  for repo in $(repos); do pgbr --repo="$repo" --type="$type" backup; done
}

init() {
  if pgbr info --output=json 2>/dev/null | grep -q '"status":{"code":0'; then
    log "stanza ev уже есть"
    return 0
  fi
  pgbr stanza-create
  pgbr check
  run full backup_all full
}

verify() {
  local repo
  pgbr check
  for repo in $(repos); do pgbr --repo="$repo" verify; done
}

restore_check_cleanup() {
  docker rm -f "${RC_NAME:-}" >/dev/null 2>&1 || true
  docker volume rm "${RC_VOLUME:-}" >/dev/null 2>&1 || true
  [[ -n "${EV_RESTORE_NETWORK:-}" ]] || docker network rm "${RC_NET:-}" >/dev/null 2>&1 || true
}

# restore-check — последний бэкап repo1 во временный том и контейнер без доступа к сети приложения;
# архивация WAL выключена (иначе копия писала бы в репозиторий production). Затем аудит целостности
# образом backend (ENVIRONMENT=test: без секретов и S3) и счётчики строк. Том и контейнер удаляются.
restore_check() {
  local name="ev-$ENV-restore-check" volume="ev-$ENV-restore-check-data"
  # Своя сеть без контейнеров приложения (S3 — через интернет); на стенде — сеть «провайдера» с MinIO.
  local net="${EV_RESTORE_NETWORK:-ev-$ENV-restore-check}"
  local image="${EV_POSTGRES_IMAGE:-ev-postgres:local}"
  RC_NAME="$name" RC_VOLUME="$volume" RC_NET="$net"
  restore_check_cleanup
  trap restore_check_cleanup EXIT
  [[ -n "${EV_RESTORE_NETWORK:-}" ]] || docker network create "$net" >/dev/null
  docker volume create "$volume" >/dev/null
  local env_args=(--env-file "$EV_SECRETS/postgres.env"
    -e "PGBACKREST_REPO1_S3_ENDPOINT=$EV_BACKUP_S3_ENDPOINT" -e "PGBACKREST_REPO1_S3_BUCKET=$EV_S3_BACKUP_BUCKET"
    -e "PGBACKREST_REPO1_S3_REGION=${EV_S3_REGION:-ru-1}")
  [[ -n "${EV_RESTORE_EXTRA_ARGS:-}" ]] && read -r -a extra <<< "$EV_RESTORE_EXTRA_ARGS" && env_args+=("${extra[@]}")
  local started
  started="$(date +%s)"
  docker run --rm --network "$net" -v "$volume:/var/lib/postgresql/data" "${env_args[@]}" -u postgres "$image" \
    pgbackrest --stanza=ev --repo=1 --archive-mode=off restore
  docker run -d --name "$name" --network "$net" -v "$volume:/var/lib/postgresql/data" "${env_args[@]}" "$image" \
    postgres -c config_file=/etc/postgresql/postgresql.conf -c archive_mode=off >/dev/null
  local waited=0
  until docker exec "$name" pg_isready -U ev -d ev_servicedesk >/dev/null 2>&1; do
    (( waited < 300 )) || { docker logs --tail 50 "$name" >&2; return 1; }
    sleep 2
    waited=$((waited + 2))
  done
  # Восстановление завершено, когда экземпляр вышел из recovery.
  until [[ "$(docker exec "$name" psql -U ev -d ev_servicedesk -Atc 'select pg_is_in_recovery()')" == f ]]; do
    (( waited < 600 )) || return 1
    sleep 2
    waited=$((waited + 2))
  done
  local seconds=$(( $(date +%s) - started ))
  docker exec "$name" psql -U ev -d ev_servicedesk -Atc \
    "select 'app_user', count(*) from app_user union all select 'vehicle', count(*) from vehicle
     union all select 'ticket', count(*) from ticket union all select 'ticket_message', count(*) from ticket_message
     union all select 'notification', count(*) from notification" | sed 's/^/restore-check: строк /' >&2
  local password
  password="$(sed -n 's/^POSTGRES_PASSWORD=//p' "$EV_SECRETS/postgres.env")"
  docker run --rm --network "$net" -e ENVIRONMENT=test \
    -e "DATABASE_URL=postgresql+psycopg://ev:${password}@${name}:5432/ev_servicedesk" \
    "$BACKEND_IMAGE" python -m app.tools.integrity >&2
  log "restore-check: восстановление и аудит — ${seconds} с"
  restore_check_cleanup
}

main() {
  local command="${1:-}"
  [[ $# -eq 2 ]] || { sed -n '2,12p' "$0" >&2; exit 2; }
  check_env_name "$2"
  ENV="$2"
  DIR="$(release_dir "$ENV" current)" || die "нет текущего выпуска $ENV"
  load_release_env "$ENV" "$DIR"
  : "${EV_TEXTFILE_DIR:?}"
  case "$command" in
    init) init ;;
    full|diff) run "$command" backup_all "$command" ;;
    verify) run verify verify ;;
    restore-check) run restore_check restore_check ;;
    info) pgbr info ;;
    *) die "неизвестная команда $command" ;;
  esac
}

main "$@"
