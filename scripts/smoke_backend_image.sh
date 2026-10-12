#!/usr/bin/env bash
# Smoke-тест образа backend (Главы 10–13, ADR 0013, 0014, 0016, 0017): запуск как в staging,
# Auth, Vehicle, Aggregates, Tickets/Uploads и WebSocket событий тикета.
# Нужен Redis на localhost:6379 (в CI — service container, локально — docker compose up -d redis).
# БД Redis 14 отведена smoke-тесту и очищается перед запуском. S3 — собственный сайдкар MinIO
# во внутренней docker-сети smoke-теста (без порта на хосте; MinIO из docker compose не
# затрагивается), удаляется вместе с сетью при выходе. Секреты и ключи MinIO — одноразовые
# случайные, передаются в контейнеры по имени переменной (-e NAME) и нигде не печатаются.
# Запуск: scripts/smoke_backend_image.sh <образ>   (например backend:smoke)

set -euo pipefail

IMAGE="${1:?Укажите образ, например backend:smoke}"
NAME="ev-backend-smoke-$$"
NOBUCKET="ev-backend-smoke-nobucket-$$"
MINIO="ev-minio-smoke-$$"
NET="ev-smoke-$$"
PORT="${SMOKE_PORT:-18000}"
BASE="http://localhost:$PORT"
# Redis хоста из контейнера: host.docker.internal (Linux — через host-gateway, macOS — штатно).
REDIS_URL="${SMOKE_REDIS_URL:-redis://host.docker.internal:6379/14}"
HOST_GW=(--add-host=host.docker.internal:host-gateway)
PHONE="+375290000001"
# Тот же закреплённый образ, что в docker-compose.yml и backend-ci.yml (ADR 0017).
MINIO_IMAGE="${SMOKE_MINIO_IMAGE:-pgsty/minio:RELEASE.2026-08-04T00-00-00Z}"
S3_BUCKET="ev-servicedesk-smoke"
FORGED='eyJhbGciOiJub25lIn0.eyJzdWIiOiIxIn0.'  # alg=none, без подписи

JWT_SECRET="$(openssl rand -hex 32)"
SMS_CODE_SECRET="$(openssl rand -hex 32)"
S3_ACCESS_KEY="smoke$(openssl rand -hex 8)"
S3_SECRET_KEY="$(openssl rand -hex 24)"
MINIO_ROOT_USER="$S3_ACCESS_KEY"
MINIO_ROOT_PASSWORD="$S3_SECRET_KEY"
MC_HOST_smoke="http://$S3_ACCESS_KEY:$S3_SECRET_KEY@localhost:9000"  # mc внутри сайдкара
export JWT_SECRET SMS_CODE_SECRET S3_ACCESS_KEY S3_SECRET_KEY MINIO_ROOT_USER MINIO_ROOT_PASSWORD \
  MC_HOST_smoke

# shellcheck disable=SC2329  # вызывается из trap
cleanup() {
  docker rm -fv "$NAME" "$NOBUCKET" "$MINIO" >/dev/null 2>&1 || true
  docker network rm "$NET" >/dev/null 2>&1 || true
}
trap cleanup EXIT

fail=0
check() { if [ "$2" = "$3" ]; then echo "PASS  $1"; else echo "FAIL  $1: ожидалось '$3', получено '$2'"; fail=1; fi; }
status() { curl -s -o /dev/null -w '%{http_code}' "$@"; }
# Логи на экран — только через redact: значения секретов заменяются на ***.
redact() {
  sed -e "s/$JWT_SECRET/***/g" -e "s/$SMS_CODE_SECRET/***/g" \
      -e "s/$S3_SECRET_KEY/***/g" -e "s/$S3_ACCESS_KEY/***/g"
}
# Окружение staging; S3 — сайдкар по имени minio во внутренней сети smoke-теста.
APP_ENV=(-e ENVIRONMENT=staging -e JWT_SECRET -e SMS_CODE_SECRET -e REDIS_URL="$REDIS_URL"
         -e S3_ENDPOINT=http://minio:9000 -e S3_BUCKET="$S3_BUCKET" -e S3_ACCESS_KEY -e S3_SECRET_KEY)
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
check "Swagger: все операции Auth Service, /me, Vehicle, Aggregates, Tickets и Uploads" \
  "$(curl -fsS "$BASE/openapi.json" | python3 -c '
import json, sys
need = {"requestPhoneCode", "verifyPhoneCode", "refreshToken", "logout", "withdrawPdConsent",
        "staffLogin", "linkTelegram", "getCurrentUser",
        "searchVehicleModels", "listVehicles", "createVehicle", "getVehicle", "deleteVehicle",
        "updateVehicleMileage", "correctVehicleMileage", "listMaintenanceRecords",
        "createMaintenanceRecord",
        "listAggregateTypes", "createAggregateType", "listMaintenanceRegulations",
        "reviseMaintenanceRegulation", "archiveMaintenanceRegulation", "listAggregateStatuses",
        "replaceAggregateStatus", "getAggregateStatusThresholds",
        "updateAggregateStatusThresholds",
        "listTickets", "createTicket", "getTicket", "updateTicketStatus", "claimTicket",
        "assignTicket", "listTicketMessages", "createTicketMessage", "createPresignedUpload"}
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

# Ключи и секреты не попадают в логи приложения — в том числе в трассировку отказа старта.
logs=$( { docker logs "$NOBUCKET"; docker logs "$NAME"; } 2>&1 )
leak=none
for secret in "$JWT_SECRET" "$SMS_CODE_SECRET" "$S3_ACCESS_KEY" "$S3_SECRET_KEY"; do
  if grep -qF "$secret" <<<"$logs"; then leak=found; fi
done
check "логи контейнеров не содержат секретов и ключей S3" "$leak" none

if [ "$fail" -ne 0 ]; then
  echo "--- логи контейнера ---"; docker logs "$NAME" 2>&1 | redact | tail -50
fi
exit $fail
