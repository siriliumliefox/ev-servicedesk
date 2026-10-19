#!/usr/bin/env bash
# Восстановление окружения на новой ВМ из бэкапа (глава 26, ADR 0030 пп. 9, 22; docs/runbooks/RESTORE.md).
#
#   restore.sh <env> <sha> [--time '2026-10-19 10:00:00+00'] [--repo 1|2]
#
# До запуска: ВМ подготовлена (bootstrap.sh), выпуск <sha> получен без включения
# (EV_RECEIVE_ONLY=1 deploy.sh receive <env> < bundle), PostgreSQL этого окружения ещё не запускался.
# Шаги: пустой том данных → pgbackrest restore (последняя точка или --time) → deploy.sh release
# (PostgreSQL догоняет WAL и выходит из recovery, миграции, up, smoke) → новый полный бэкап.
# Итог — RTO (от начала восстановления до PASS smoke) в журнале.
set -euo pipefail
# shellcheck source=lib.sh
. "$(cd "$(dirname "$0")" && pwd)/lib.sh"

[[ $# -ge 2 ]] || { sed -n '2,10p' "$0" >&2; exit 2; }
ENV="$1"
SHA="$2"
shift 2
check_env_name "$ENV"
check_sha "$SHA"
TARGET_TIME=""
REPO=1
while [[ $# -gt 0 ]]; do
  case "$1" in
    --time) TARGET_TIME="$2"; shift 2 ;;
    --repo) REPO="$2"; shift 2 ;;
    *) die "неизвестный параметр $1" ;;
  esac
done
[[ "$REPO" == 1 || "$REPO" == 2 ]] || die "--repo — 1 или 2"

DIR="$(release_dir "$ENV" "$SHA")" || die "нет выпуска $SHA — сначала EV_RECEIVE_ONLY=1 deploy.sh receive"
load_release_env "$ENV" "$DIR"
started="$(date +%s)"
volume="ev-${ENV}_pgdata"

if docker ps -q --filter "label=com.docker.compose.project=ev-$ENV" --filter "label=com.docker.compose.service=postgres" | grep -q .; then
  die "PostgreSQL ev-$ENV уже запущен — восстановление только в пустой том (остановите и удалите том осознанно)"
fi
if docker volume inspect "$volume" >/dev/null 2>&1; then
  die "том $volume уже существует — восстановление только в пустой том"
fi
# Том создаётся с метками compose — дальше им управляет проект ev-<env>.
docker volume create --label "com.docker.compose.project=ev-$ENV" --label com.docker.compose.volume=pgdata "$volume" >/dev/null

restore_args=(--stanza=ev "--repo=$REPO" restore)
if [[ -n "$TARGET_TIME" ]]; then
  restore_args+=(--type=time "--target=$TARGET_TIME" --target-action=promote)
fi
log "восстановление ev-$ENV из repo$REPO${TARGET_TIME:+ на $TARGET_TIME}"
network_args=()
[[ -n "${EV_RESTORE_NETWORK:-}" ]] && network_args=(--network "$EV_RESTORE_NETWORK")
extra=()
[[ -n "${EV_RESTORE_EXTRA_ARGS:-}" ]] && read -r -a extra <<< "$EV_RESTORE_EXTRA_ARGS"
docker run --rm "${network_args[@]+"${network_args[@]}"}" -v "$volume:/var/lib/postgresql/data" \
  --env-file "$EV_SECRETS/postgres.env" \
  -e "PGBACKREST_REPO1_S3_ENDPOINT=$EV_BACKUP_S3_ENDPOINT" -e "PGBACKREST_REPO1_S3_BUCKET=$EV_S3_BACKUP_BUCKET" \
  -e "PGBACKREST_REPO1_S3_REGION=${EV_S3_REGION:-ru-1}" "${extra[@]+"${extra[@]}"}" \
  -u postgres "${EV_POSTGRES_IMAGE:-ev-postgres:local}" pgbackrest "${restore_args[@]}"

"$(dirname "$0")/deploy.sh" release "$ENV" "$SHA"
rto=$(( $(date +%s) - started ))
log "PASS восстановление ev-$ENV: RTO ${rto} с (цель ≤ 7200 с)"
"$(dirname "$0")/backup.sh" full "$ENV" || log "предупреждение: полный бэкап после восстановления не выполнен"
