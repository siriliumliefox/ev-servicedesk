#!/usr/bin/env bash
# Smoke-тест образа backend (Главы 10–17, ADR 0013, 0014, 0016–0021): запуск как в
# staging, Auth, Vehicle, Aggregates, Tickets/Uploads, WebSocket событий тикета, Knowledge Base,
# Notifications и worker уведомлений, Analytics — сверка с контрольным набором (ADR 0020 п. 9).
# Нужен Redis на localhost:6379 (в CI — service container, локально — docker compose up -d redis).
# БД Redis 14 отведена smoke-тесту и очищается перед запуском. S3 — собственный сайдкар MinIO
# во внутренней docker-сети smoke-теста (без порта на хосте; MinIO из docker compose не
# затрагивается), удаляется вместе с сетью при выходе. Так же — сайдкар PostgreSQL для миграций
# и контрольного набора аналитики (каталог backend/tests монтируется только в разовые контейнеры
# загрузки и сверки — в образ тесты не входят). Секреты и ключи MinIO — одноразовые
# случайные, передаются в контейнеры по имени переменной (-e NAME) и нигде не печатаются.
# Запуск: scripts/smoke_backend_image.sh <образ>   (например backend:smoke)

set -euo pipefail

IMAGE="${1:?Укажите образ, например backend:smoke}"
NAME="ev-backend-smoke-$$"
NOBUCKET="ev-backend-smoke-nobucket-$$"
MINIO="ev-minio-smoke-$$"
PG="ev-postgres-smoke-$$"
NET="ev-smoke-$$"
PORT="${SMOKE_PORT:-18000}"
BASE="http://localhost:$PORT"
# Redis хоста из контейнера: host.docker.internal (Linux — через host-gateway, macOS — штатно).
REDIS_URL="${SMOKE_REDIS_URL:-redis://host.docker.internal:6379/14}"
HOST_GW=(--add-host=host.docker.internal:host-gateway)
PHONE="+375290000001"
# Образ MinIO — закреплённый в docker-compose.yml (x-minio-image, ADR 0017); SMOKE_MINIO_IMAGE
# подменяет его. Конфигурация compose читается целиком, наружу выводится только образ.
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MINIO_IMAGE="${SMOKE_MINIO_IMAGE:-$(docker compose -f "$ROOT/docker-compose.yml" config --format json minio \
  | python3 -c 'import json, sys; print(json.load(sys.stdin)["services"]["minio"]["image"])')}"
if [ -z "$MINIO_IMAGE" ]; then
  echo "FAIL  образ MinIO не найден в docker-compose.yml"; exit 1
fi
PG_IMAGE="${SMOKE_POSTGRES_IMAGE:-$(docker compose -f "$ROOT/docker-compose.yml" config --format json postgres \
  | python3 -c 'import json, sys; print(json.load(sys.stdin)["services"]["postgres"]["image"])')}"
S3_BUCKET="ev-servicedesk-smoke"
FORGED='eyJhbGciOiJub25lIn0.eyJzdWIiOiIxIn0.'  # alg=none, без подписи

JWT_SECRET="$(openssl rand -hex 32)"
SMS_CODE_SECRET="$(openssl rand -hex 32)"
S3_ACCESS_KEY="smoke$(openssl rand -hex 8)"
S3_SECRET_KEY="$(openssl rand -hex 24)"
MINIO_ROOT_USER="$S3_ACCESS_KEY"
MINIO_ROOT_PASSWORD="$S3_SECRET_KEY"
MC_HOST_smoke="http://$S3_ACCESS_KEY:$S3_SECRET_KEY@localhost:9000"  # mc внутри сайдкара
POSTGRES_PASSWORD="$(openssl rand -hex 24)"
DATABASE_URL="postgresql+psycopg://smoke:$POSTGRES_PASSWORD@postgres:5432/smoke"
CONTROL_ADMIN_PASSWORD="$(openssl rand -hex 16)"  # администратор контрольного набора аналитики
export JWT_SECRET SMS_CODE_SECRET S3_ACCESS_KEY S3_SECRET_KEY MINIO_ROOT_USER MINIO_ROOT_PASSWORD \
  MC_HOST_smoke POSTGRES_PASSWORD DATABASE_URL CONTROL_ADMIN_PASSWORD

# shellcheck disable=SC2329  # вызывается из trap
cleanup() {
  docker rm -fv "$NAME" "$NOBUCKET" "$MINIO" "$PG" >/dev/null 2>&1 || true
  docker network rm "$NET" >/dev/null 2>&1 || true
}
trap cleanup EXIT

fail=0
check() { if [ "$2" = "$3" ]; then echo "PASS  $1"; else echo "FAIL  $1: ожидалось '$3', получено '$2'"; fail=1; fi; }
status() { curl -s -o /dev/null -w '%{http_code}' "$@"; }
# Логи на экран — только через redact: значения секретов заменяются на ***.
redact() {
  sed -e "s/$JWT_SECRET/***/g" -e "s/$SMS_CODE_SECRET/***/g" \
      -e "s/$S3_SECRET_KEY/***/g" -e "s/$S3_ACCESS_KEY/***/g" \
      -e "s/$POSTGRES_PASSWORD/***/g" -e "s/$CONTROL_ADMIN_PASSWORD/***/g"
}
# Окружение staging; S3 — сайдкар по имени minio во внутренней сети smoke-теста.
APP_ENV=(-e ENVIRONMENT=staging -e JWT_SECRET -e SMS_CODE_SECRET -e REDIS_URL="$REDIS_URL"
         -e S3_ENDPOINT=http://minio:9000 -e S3_BUCKET="$S3_BUCKET" -e S3_ACCESS_KEY -e S3_SECRET_KEY
         -e DATABASE_URL)
# Контейнер приложения: основная сеть — bridge по умолчанию (как раньше: публикация порта и
# Redis хоста через host-gateway), плюс внутренняя сеть с MinIO — подключается до старта,
# потому что бакет проверяется при старте (ADR 0017 п. 11).
start_app() {
  local name="$1"; shift
  docker create --name "$name" "${HOST_GW[@]}" "${APP_ENV[@]}" "$@" "$IMAGE" >/dev/null
  docker network connect "$NET" "$name"
  docker start "$name" >/dev/null
}

# Повторяемость: счётчики лимитов прошлого прогона не должны влиять на результат.
docker run --rm "${HOST_GW[@]}" redis:7-alpine redis-cli -u "$REDIS_URL" FLUSHDB >/dev/null

# Fail closed: без ENVIRONMENT образ — production и с секретами-заглушками не стартует,
# причём именно из-за проверки настроек, а не из-за посторонней ошибки импорта.
out=$(docker run --rm "$IMAGE" python -c "import app.main" 2>&1) && r=started || r=refused
if [ "$r" = refused ] && ! grep -q 'ENVIRONMENT=production: JWT_SECRET, SMS_CODE_SECRET' <<<"$out"; then
  r="refused-other-reason"
fi
check "образ без ENVIRONMENT не стартует (production, нет секретов)" "$r" refused

# Worker уведомлений (ADR 0019): в production без FCM — отказ на проверке настроек, даже если
# остальные секреты заданы (фейковый push в production запрещён).
out=$(docker run --rm -e JWT_SECRET -e SMS_CODE_SECRET -e S3_ACCESS_KEY -e S3_SECRET_KEY \
        -e SMS_PROVIDER=a1 -e SMS_PROVIDER_USER=375290000000 -e SMS_PROVIDER_API_KEY=smoke \
        "$IMAGE" python -m app.workers.notifications 2>&1) && r=started || r=refused
if [ "$r" = refused ] && ! grep -q 'ENVIRONMENT=production: PUSH_PROVIDER=fake' <<<"$out"; then
  r="refused-other-reason"
fi
check "worker уведомлений в production без FCM не стартует" "$r" refused

# Тестовые номера SMS (ADR 0021 п. 6) в production запрещены — отказ на проверке настроек.
out=$(docker run --rm -e SMS_TEST_PHONES=+375290009001 -e SMS_TEST_CODE=1234 \
        "$IMAGE" python -c "import app.main" 2>&1) && r=started || r=refused
if [ "$r" = refused ] && ! grep -q 'SMS_TEST_PHONES запрещены в production' <<<"$out"; then
  r="refused-other-reason"
fi
check "тестовые номера SMS в production — образ не стартует" "$r" refused

# Сайдкар MinIO: внутренняя сеть (без выхода наружу и без порта на хосте).
docker network create --internal "$NET" >/dev/null
docker run -d --name "$MINIO" --network "$NET" --network-alias minio \
  -e MINIO_ROOT_USER -e MINIO_ROOT_PASSWORD "$MINIO_IMAGE" server /data >/dev/null
minio=down
for _ in $(seq 1 30); do
  docker exec "$MINIO" curl -fsS http://localhost:9000/minio/health/live >/dev/null 2>&1 \
    && { minio=up; break; }
  sleep 1
done
if [ "$minio" != up ]; then
  echo "FAIL  MinIO-сайдкар не поднялся"; docker logs "$MINIO" 2>&1 | redact | tail -50; exit 1
fi

# Сайдкар PostgreSQL (образ — как в docker-compose.yml): миграции и контрольный набор аналитики.
docker run -d --name "$PG" --network "$NET" --network-alias postgres \
  -e POSTGRES_USER=smoke -e POSTGRES_DB=smoke -e POSTGRES_PASSWORD "$PG_IMAGE" >/dev/null
pg=down
for _ in $(seq 1 30); do
  docker exec "$PG" pg_isready -U smoke -d smoke >/dev/null 2>&1 && { pg=up; break; }
  sleep 1
done
if [ "$pg" != up ]; then
  echo "FAIL  PostgreSQL-сайдкар не поднялся"; docker logs "$PG" 2>&1 | redact | tail -50; exit 1
fi

# Fail closed: staging с настроенным S3, но без бакета не стартует — и именно потому, что
# MinIO ответил «бакета нет» (HTTP 404), а не из-за сети или посторонней ошибки.
start_app "$NOBUCKET"
for _ in $(seq 1 30); do
  [ "$(docker inspect -f '{{.State.Running}}' "$NOBUCKET")" = false ] && break
  sleep 1
done
if [ "$(docker inspect -f '{{.State.Running}}' "$NOBUCKET")" = true ]; then
  r=started
elif [ "$(docker inspect -f '{{.State.ExitCode}}' "$NOBUCKET")" = 0 ]; then
  r=exited-0
elif grep -q 'Бакет S3 недоступен (HTTP 404)' <<<"$(docker logs "$NOBUCKET" 2>&1)"; then
  r=refused
else
  r=refused-other-reason
fi
check "staging без бакета S3 не стартует (fail closed, ADR 0017 п. 11)" "$r" refused

if ! docker exec -e MC_HOST_smoke "$MINIO" mc mb "smoke/$S3_BUCKET" >/dev/null 2>&1; then
  echo "FAIL  не удалось создать бакет в MinIO-сайдкаре"; exit 1
fi

start_app "$NAME" -p "$PORT:8000"

for _ in $(seq 1 30); do
  curl -fsS "$BASE/health" >/dev/null 2>&1 && break
  sleep 1
done

check "/health отвечает, окружение staging" \
  "$(curl -fsS "$BASE/health" | python3 -c 'import json,sys; print(json.load(sys.stdin)["environment"])')" staging
check "Swagger: все операции Auth, Users, Vehicle, Aggregates, Tickets, Uploads, KnowledgeBase, Notifications, Analytics" \
  "$(curl -fsS "$BASE/openapi.json" | python3 -c '
import json, sys
need = {"requestPhoneCode", "verifyPhoneCode", "refreshToken", "logout", "withdrawPdConsent",
        "staffLogin", "linkTelegram", "getCurrentUser",
        "listUsers", "createStaffUser", "getUser", "updateUser",
        "searchVehicleModels", "listVehicles", "createVehicle", "getVehicle", "deleteVehicle",
        "updateVehicleMileage", "correctVehicleMileage", "listMaintenanceRecords",
        "createMaintenanceRecord",
        "listAggregateTypes", "createAggregateType", "listMaintenanceRegulations",
        "reviseMaintenanceRegulation", "archiveMaintenanceRegulation", "listAggregateStatuses",
        "replaceAggregateStatus", "getAggregateStatusThresholds",
        "updateAggregateStatusThresholds",
        "listTickets", "createTicket", "getTicket", "updateTicketStatus", "claimTicket",
        "assignTicket", "listTicketMessages", "createTicketMessage", "createPresignedUpload",
        "listKnowledgeArticles", "createKnowledgeArticle", "getKnowledgeArticle",
        "updateKnowledgeArticle", "unpublishKnowledgeArticle", "listKnowledgeArticleRevisions",
        "getKnowledgeArticleRevision", "listDecisionTreeNodes", "createDecisionTreeNode",
        "validateDecisionTree", "updateDecisionTreeNode", "deleteDecisionTreeNode",
        "registerPushToken", "deletePushToken", "listNotifications", "createNotification",
        "listPublishedNotifications", "previewNotificationAudience", "markNotificationRead",
        "markNotificationOpened", "listFirmwareReleases", "createFirmwareRelease",
        "setVehicleFirmware",
        "getTicketResolutionStats", "listProblemModels", "getMaintenanceConversionStats"}
ops = {o["operationId"] for p in json.load(sys.stdin)["paths"].values() for o in p.values()}
print("ok" if need <= ops else sorted(need - ops))')" ok
check "POST /v1/auth/phone/request-code → 200" \
  "$(status -X POST "$BASE/v1/auth/phone/request-code" -H 'Content-Type: application/json' \
      -d "{\"phone\":\"$PHONE\"}")" 200
check "повторный запрос кода → 429 (rate limit)" \
  "$(status -X POST "$BASE/v1/auth/phone/request-code" -H 'Content-Type: application/json' \
      -d "{\"phone\":\"$PHONE\"}")" 429
check "GET /v1/me без токена → 401" "$(status "$BASE/v1/me")" 401
check "GET /v1/me с подделанным токеном → 401" \
  "$(status -H "Authorization: Bearer $FORGED" "$BASE/v1/me")" 401
check "GET /v1/vehicles без токена → 401" "$(status "$BASE/v1/vehicles")" 401
check "POST /v1/vehicles с подделанным токеном → 401" \
  "$(status -X POST "$BASE/v1/vehicles" -H 'Content-Type: application/json' \
      -H "Authorization: Bearer $FORGED" \
      -d '{"vin":"L6TZ0010000000001"}')" 401
check "GET /v1/aggregate-types без токена → 401" "$(status "$BASE/v1/aggregate-types")" 401
check "GET /v1/tickets без токена → 401" "$(status "$BASE/v1/tickets")" 401
check "GET /v1/knowledge-articles без токена → 401" "$(status "$BASE/v1/knowledge-articles")" 401
check "PATCH /v1/decision-tree-nodes/1 с подделанным токеном → 401" \
  "$(status -X PATCH "$BASE/v1/decision-tree-nodes/1" -H 'Content-Type: application/json' \
      -H "Authorization: Bearer $FORGED" \
      -d '{"question_text":"x","is_root":true,"is_escalation":false}')" 401
check "GET /v1/notifications без токена → 401" "$(status "$BASE/v1/notifications")" 401
check "POST /v1/push-tokens с подделанным токеном → 401" \
  "$(status -X POST "$BASE/v1/push-tokens" -H 'Content-Type: application/json' \
      -H "Authorization: Bearer $FORGED" -d '{"token":"smoke"}')" 401
check "POST /v1/firmware-releases без токена → 401" \
  "$(status -X POST "$BASE/v1/firmware-releases" -H 'Content-Type: application/json' \
      -d '{"vehicle_model_id":1,"version":"1.0","released_at":"2026-01-01"}')" 401
check "GET /v1/analytics/ticket-resolution без токена → 401" \
  "$(status "$BASE/v1/analytics/ticket-resolution?date_from=2026-03-01&date_to=2026-03-31")" 401
# Worker в staging: модуль и фейковый отправитель поднимаются в том же образе.
check "worker уведомлений: staging без Firebase — фейковый push" \
  "$(docker exec "$NAME" python -c \
      "from app.core.config import get_settings; from app.domain.notifications.push import get_push_sender; import app.workers.notifications; print(type(get_push_sender(get_settings())).__name__)")" FakePushSender
check "POST /v1/uploads/presign без токена → 401" \
  "$(status -X POST "$BASE/v1/uploads/presign" -H 'Content-Type: application/json' \
      -d '{"file_name":"photo.jpg","file_type":"photo"}')" 401
# 404 по HTTP ничего не доказывает — проверяем таблицу маршрутов приложения в контейнере.
check "отладочный маршрут SMS-кода не подключён вне local" \
  "$(docker exec "$NAME" python -c \
      "from app.main import app; print(any('_debug' in getattr(r, 'path', '') for r in app.routes))")" False

# WebSocket: клиент — websockets из самого образа (версия закреплена poetry.lock; та же
# библиотека обслуживает WebSocket в uvicorn), подключение изнутри контейнера. Без кадра auth
# за ws_auth_timeout_seconds и с подделанным токеном сокет закрывается кодом 4401 (ADR 0017
# п. 9, docs/asyncapi.yaml). Оба случая — параллельно; ошибка рукопожатия — тоже провал.
read -r -d '' WS_CLIENT <<'PY' || true
import asyncio, json, os
from websockets.asyncio.client import connect
from websockets.exceptions import ConnectionClosed, InvalidStatus

URL = "ws://localhost:8000/v1/tickets/1/ws"


async def close_code(frame):
    try:
        async with connect(URL, open_timeout=10, proxy=None) as ws:
            if frame is not None:
                await ws.send(frame)
            try:
                await asyncio.wait_for(ws.recv(), 30)
            except ConnectionClosed as exc:
                return str(exc.rcvd.code) if exc.rcvd else "no-close-frame"
            return "frame-instead-of-close"
    except InvalidStatus as exc:
        return f"handshake-{exc.response.status_code}"
    except Exception as exc:
        return type(exc).__name__


async def main():
    forged = json.dumps({"type": "auth", "access_token": os.environ["FORGED"]})
    print(*await asyncio.gather(close_code(None), close_code(forged)))


asyncio.run(main())
PY
ws=$(docker exec -e FORGED="$FORGED" "$NAME" python -c "$WS_CLIENT" 2>&1) || true
read -r ws_silent ws_forged <<<"$ws" || true
check "WS /v1/tickets/1/ws без кадра auth → закрытие 4401" "${ws_silent:-}" 4401
check "WS /v1/tickets/1/ws с подделанным токеном → закрытие 4401" "${ws_forged:-}" 4401
if [ "${ws_silent:-} ${ws_forged:-}" != "4401 4401" ]; then
  echo "--- вывод WS-клиента ---"; redact <<<"$ws" | tail -20
fi

# Analytics (ADR 0020 п. 9): миграции образа на PostgreSQL-сайдкаре, контрольный набор,
# обновление витрины worker аналитики образа и сверка ответов API с ручным расчётом
# (docs/ANALYTICS_CONTROL.md). Каталог тестов — только в разовых контейнерах загрузки и сверки.
CONTROL=(docker run --rm --network "$NET" "${APP_ENV[@]}" -e CONTROL_ADMIN_PASSWORD
         -v "$ROOT/backend/tests:/app/tests:ro" "$IMAGE" python -m tests.support.analytics_control)
docker exec "$NAME" alembic upgrade head >/dev/null 2>&1 && r=ok || r=failed
check "миграции образа применяются (alembic upgrade head)" "$r" ok
"${CONTROL[@]}" load >/dev/null 2>&1 && r=ok || r=failed
check "контрольный набор аналитики загружен" "$r" ok
docker exec "$NAME" python -m app.workers.analytics --once >/dev/null 2>&1 && r=ok || r=failed
check "worker аналитики: витрина обновлена (--once)" "$r" ok
control=$("${CONTROL[@]}" verify --base "http://$NAME:8000" 2>&1) && r=ok || r=failed
redact <<<"$control" | grep -E '^(PASS|FAIL|      )' || true
check "показатели аналитики совпадают с ручным расчётом (14 запросов)" \
  "$r $(grep -c '^PASS  контроль аналитики' <<<"$control" || true)" "ok 14"
if [ "$r" != ok ]; then redact <<<"$control" | tail -20; fi

# Ключи и секреты не попадают в логи приложения — в том числе в трассировку отказа старта.
logs=$( { docker logs "$NOBUCKET"; docker logs "$NAME"; } 2>&1 )
leak=none
for secret in "$JWT_SECRET" "$SMS_CODE_SECRET" "$S3_ACCESS_KEY" "$S3_SECRET_KEY" \
              "$POSTGRES_PASSWORD" "$CONTROL_ADMIN_PASSWORD"; do
  if grep -qF "$secret" <<<"$logs"; then leak=found; fi
done
check "логи контейнеров не содержат секретов, ключей S3 и паролей БД" "$leak" none

if [ "$fail" -ne 0 ]; then
  echo "--- логи контейнера ---"; docker logs "$NAME" 2>&1 | redact | tail -50
fi
exit $fail
