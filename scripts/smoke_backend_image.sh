#!/usr/bin/env bash
# Smoke-тест образа backend (Глава 10, ADR 0013): запуск как в staging и проверка Auth Service.
# Нужен Redis на localhost:6379 (в CI — service container, локально — docker compose up -d redis).
# Секреты — одноразовые случайные, нигде не печатаются.
# Запуск: scripts/smoke_backend_image.sh <образ>   (например backend:smoke)

set -euo pipefail

IMAGE="${1:?Укажите образ, например backend:smoke}"
NAME="ev-backend-smoke-$$"
PORT="${SMOKE_PORT:-18000}"
BASE="http://localhost:$PORT"
# Redis хоста из контейнера: host.docker.internal (Linux — через host-gateway, macOS — штатно).
REDIS_URL="${SMOKE_REDIS_URL:-redis://host.docker.internal:6379/14}"

cleanup() { docker rm -f "$NAME" >/dev/null 2>&1 || true; }
trap cleanup EXIT

docker run -d --name "$NAME" -p "$PORT:8000" --add-host=host.docker.internal:host-gateway \
  -e ENVIRONMENT=staging \
  -e JWT_SECRET="$(openssl rand -hex 32)" \
  -e SMS_CODE_SECRET="$(openssl rand -hex 32)" \
  -e REDIS_URL="$REDIS_URL" \
  "$IMAGE" >/dev/null

for _ in $(seq 1 30); do
  curl -fsS "$BASE/health" >/dev/null 2>&1 && break
  sleep 1
done

fail=0
check() { if [ "$2" = "$3" ]; then echo "PASS  $1"; else echo "FAIL  $1: ожидалось '$3', получено '$2'"; fail=1; fi; }
status() { curl -s -o /dev/null -w '%{http_code}' "$@"; }

check "/health отвечает, окружение staging" \
  "$(curl -fsS "$BASE/health" | python3 -c 'import json,sys; print(json.load(sys.stdin)["environment"])')" staging
check "Swagger: все операции Auth Service и /me" \
  "$(curl -fsS "$BASE/openapi.json" | python3 -c '
import json, sys
need = {"requestPhoneCode", "verifyPhoneCode", "refreshToken", "logout", "withdrawPdConsent",
        "staffLogin", "linkTelegram", "getCurrentUser"}
ops = {o["operationId"] for p in json.load(sys.stdin)["paths"].values() for o in p.values()}
print("ok" if need <= ops else sorted(need - ops))')" ok
check "POST /v1/auth/phone/request-code → 200" \
  "$(status -X POST "$BASE/v1/auth/phone/request-code" -H 'Content-Type: application/json' \
      -d '{"phone":"+375290000001"}')" 200
check "повторный запрос кода → 429 (rate limit)" \
  "$(status -X POST "$BASE/v1/auth/phone/request-code" -H 'Content-Type: application/json' \
      -d '{"phone":"+375290000001"}')" 429
check "GET /v1/me без токена → 401" "$(status "$BASE/v1/me")" 401
check "GET /v1/me с подделанным токеном → 401" \
  "$(status -H 'Authorization: Bearer eyJhbGciOiJub25lIn0.eyJzdWIiOiIxIn0.' "$BASE/v1/me")" 401
check "отладочного маршрута вне local нет → 404" \
  "$(status "$BASE/v1/_debug/sms/last-code?phone=%2B375290000001")" 404

if [ "$fail" -ne 0 ]; then
  echo "--- логи контейнера ---"; docker logs "$NAME" 2>&1 | tail -50
fi
exit $fail
