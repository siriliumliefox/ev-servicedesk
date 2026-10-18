#!/usr/bin/env bash
# Страж плана отката (глава 26, ADR 0030 п. 16): предыдущий выпуск backend работает на схеме кандидата.
#
#   scripts/rollback_compat.sh <образ-кандидат> <предыдущий-образ>
#
# Откат меняет образ, схема остаётся (миграции совместимы с предыдущим выпуском: expand → contract).
# Проверка: схема предыдущего выпуска → миграции кандидата → предыдущий образ: API стартует (preflight,
# /health, 401 без токена), ORM читает каждую таблицу, аудит целостности проходит. Несовместимая
# миграция (удалён или переименован столбец, который читает предыдущий выпуск) — FAIL: такой релиз
# требует downgrade при откате и помечается в PR (docs/runbooks/ROLLBACK.md).
# Сайдкары PostgreSQL, Redis и MinIO — во внутренней сети, секреты одноразовые, не печатаются.
set -euo pipefail

CANDIDATE="${1:?образ-кандидат}"
PREVIOUS="${2:?предыдущий образ}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
NET="ev-rollback-compat-$$"
PG="ev-rc-postgres-$$"
REDIS="ev-rc-redis-$$"
MINIO="ev-rc-minio-$$"
API="ev-rc-api-$$"
PORT="${ROLLBACK_COMPAT_PORT:-18100}"
image_of() {
  docker compose -f "$ROOT/docker-compose.yml" config --format json "$1" \
    | python3 -c "import json, sys; print(json.load(sys.stdin)['services']['$1']['image'])"
}
PG_IMAGE="$(image_of postgres)"
REDIS_IMAGE="$(image_of redis)"
MINIO_IMAGE="$(image_of minio)"

POSTGRES_PASSWORD="$(openssl rand -hex 24)"
S3_ACCESS_KEY="rc$(openssl rand -hex 8)"
S3_SECRET_KEY="$(openssl rand -hex 24)"
JWT_SECRET="$(openssl rand -hex 32)"
SMS_CODE_SECRET="$(openssl rand -hex 32)"
DATABASE_URL="postgresql+psycopg://ev:$POSTGRES_PASSWORD@$PG:5432/ev"
export POSTGRES_PASSWORD S3_ACCESS_KEY S3_SECRET_KEY JWT_SECRET SMS_CODE_SECRET DATABASE_URL
MINIO_ROOT_USER="$S3_ACCESS_KEY" MINIO_ROOT_PASSWORD="$S3_SECRET_KEY"
export MINIO_ROOT_USER MINIO_ROOT_PASSWORD

# shellcheck disable=SC2329  # вызывается из trap
cleanup() {
  docker rm -fv "$API" "$PG" "$REDIS" "$MINIO" >/dev/null 2>&1 || true
  docker network rm "$NET" >/dev/null 2>&1 || true
}
trap cleanup EXIT

app_env=(-e ENVIRONMENT=staging -e DATABASE_URL -e JWT_SECRET -e SMS_CODE_SECRET -e S3_ACCESS_KEY -e S3_SECRET_KEY
  -e "REDIS_URL=redis://$REDIS:6379/0" -e "S3_ENDPOINT=http://$MINIO:9000" -e S3_BUCKET=ev-rc -e SMS_PROVIDER=fake
  -e PUSH_PROVIDER=fake)
run_app() { docker run --rm --network "$NET" "${app_env[@]}" "$@"; }

docker network create "$NET" >/dev/null
docker run -d --name "$PG" --network "$NET" -e POSTGRES_USER=ev -e POSTGRES_DB=ev -e POSTGRES_PASSWORD "$PG_IMAGE" >/dev/null
docker run -d --name "$REDIS" --network "$NET" "$REDIS_IMAGE" >/dev/null
docker run -d --name "$MINIO" --network "$NET" -e MINIO_ROOT_USER -e MINIO_ROOT_PASSWORD "$MINIO_IMAGE" server /data >/dev/null
for _ in $(seq 1 60); do docker exec "$PG" pg_isready -U ev -d ev >/dev/null 2>&1 && break; sleep 1; done
for _ in $(seq 1 60); do docker exec "$MINIO" curl -fsS http://localhost:9000/minio/health/live >/dev/null 2>&1 && break; sleep 1; done
docker exec -e "MC_HOST_rc=http://$S3_ACCESS_KEY:$S3_SECRET_KEY@localhost:9000" "$MINIO" mc mb rc/ev-rc >/dev/null

run_app "$PREVIOUS" alembic upgrade head >/dev/null 2>&1 || { echo "FAIL  миграции предыдущего выпуска"; exit 1; }
before="$(docker exec "$PG" psql -U ev -d ev -Atc 'select version_num from alembic_version')"
run_app "$CANDIDATE" alembic upgrade head >/dev/null 2>&1 || { echo "FAIL  миграции кандидата"; exit 1; }
after="$(docker exec "$PG" psql -U ev -d ev -Atc 'select version_num from alembic_version')"
echo "PASS  схема предыдущего выпуска $before → кандидата $after"

docker run -d --name "$API" --network "$NET" "${app_env[@]}" -p "127.0.0.1:$PORT:8000" "$PREVIOUS" >/dev/null
ok=""
for _ in $(seq 1 60); do
  if curl -fsS "http://127.0.0.1:$PORT/health" >/dev/null 2>&1; then ok=1; break; fi
  sleep 1
done
[[ -n "$ok" ]] || { echo "FAIL  предыдущий образ не стартует на схеме кандидата:"; docker logs --tail 20 "$API" 2>&1 | sed 's/^/      /'; exit 1; }
echo "PASS  предыдущий образ стартует на схеме кандидата (/health)"
status="$(curl -s -o /dev/null -w '%{http_code}' "http://127.0.0.1:$PORT/v1/me")"
[[ "$status" == 401 ]] || { echo "FAIL  /v1/me без токена — $status"; exit 1; }
echo "PASS  /v1/me без токена — 401"

run_app -e ENVIRONMENT=test "$PREVIOUS" python -c '
from sqlalchemy import select
from app.core.db import get_session_scope
from app.models import Base
with get_session_scope()() as db:
    mappers = list(Base.registry.mappers)
    for mapper in mappers:
        db.execute(select(mapper.class_).limit(1)).all()
print(f"PASS  ORM предыдущего выпуска читает все таблицы ({len(mappers)})")
' || { echo "FAIL  ORM предыдущего выпуска не читает схему кандидата"; exit 1; }
run_app -e ENVIRONMENT=test "$PREVIOUS" python -m app.tools.integrity >/dev/null \
  || { echo "FAIL  аудит целостности предыдущим выпуском"; exit 1; }
echo "PASS  аудит целостности предыдущим выпуском на схеме кандидата"
