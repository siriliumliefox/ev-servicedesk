#!/usr/bin/env bash
# Интеграционный стек backend (Глава 17, ADR 0021 п. 1, 8, 9): все сервисы из ОДНОГО
# образа-кандидата в режиме ENVIRONMENT=staging — миграции, API, worker уведомлений, worker
# аналитики, PostgreSQL, Redis, MinIO (docker-compose.yml + docker-compose.integration.yml,
# отдельный проект: свои тома и сеть, порты инфраструктуры наружу не публикуются). На стеке —
# сквозной сценарий backend/scripts/e2e_backend.py (каждый ответ сверяется с контрактом) и
# аудит целостности. Секреты, ключи MinIO, пароль БД и код тестового номера — одноразовые
# случайные; передаются через временный файл окружения и нигде не печатаются; логи — через
# redact и проверяются на утечку. Стек удаляется при выходе (тома тоже).
# Нужны: docker compose ≥ 2.24 (!reset), poetry-окружение backend (dev-зависимости).
# Запуск: scripts/integration_stack.sh <образ>   (например backend:smoke)

set -euo pipefail

IMAGE="${1:?Укажите образ, например backend:smoke}"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PROJECT="ev-integration-$$"
PORT="${INTEGRATION_PORT:-18080}"
E2E_PHONE="+375290009001"  # тестовый номер стека: SMS не отправляется (ADR 0021 п. 6)

ENV_FILE="$(mktemp)"
chmod 600 "$ENV_FILE"
JWT_SECRET="$(openssl rand -hex 32)"
SMS_CODE_SECRET="$(openssl rand -hex 32)"
E2E_CODE="$(python3 -c 'import secrets; print(f"{secrets.randbelow(10**4):04d}")')"
S3_ACCESS_KEY="integ$(openssl rand -hex 8)"
S3_SECRET_KEY="$(openssl rand -hex 24)"
POSTGRES_PASSWORD="$(openssl rand -hex 24)"
cat >"$ENV_FILE" <<EOF
JWT_SECRET=$JWT_SECRET
SMS_CODE_SECRET=$SMS_CODE_SECRET
SMS_PROVIDER=fake
PUSH_PROVIDER=fake
SMS_TEST_PHONES=$E2E_PHONE
SMS_TEST_CODE=$E2E_CODE
EOF

# Подстановки docker-compose.yml: образ, окружение, файл секретов, ключи MinIO, БД.
export BACKEND_IMAGE="$IMAGE" BACKEND_ENV_FILE="$ENV_FILE" ENVIRONMENT=staging \
  INTEGRATION_PORT="$PORT" S3_ACCESS_KEY S3_SECRET_KEY S3_BUCKET=ev-servicedesk-integration \
  POSTGRES_USER=integration POSTGRES_PASSWORD POSTGRES_DB=ev_servicedesk_integration
COMPOSE=(docker compose -p "$PROJECT" -f "$ROOT/docker-compose.yml"
         -f "$ROOT/docker-compose.integration.yml" --profile full)

redact() {
  sed -e "s/$JWT_SECRET/***/g" -e "s/$SMS_CODE_SECRET/***/g" -e "s/$S3_SECRET_KEY/***/g" \
      -e "s/$S3_ACCESS_KEY/***/g" -e "s/$POSTGRES_PASSWORD/***/g"
}
# shellcheck disable=SC2329  # вызывается из trap
cleanup() {
  "${COMPOSE[@]}" down -v --remove-orphans >/dev/null 2>&1 || true
  rm -f "$ENV_FILE"
}
trap cleanup EXIT

fail=0
show_logs() {
  echo "--- логи стека (последние строки, секреты скрыты) ---"
  "${COMPOSE[@]}" logs --no-color --tail 80 2>&1 | redact
}

echo "Стек: образ $IMAGE, проект $PROJECT, API http://127.0.0.1:$PORT"
if ! "${COMPOSE[@]}" up -d --no-build --wait --wait-timeout 180 >/dev/null 2>&1; then
  echo "FAIL  стек не поднялся (миграции, healthcheck API, worker'ы)"
  "${COMPOSE[@]}" ps -a 2>&1 | redact
  show_logs
  exit 1
fi
echo "PASS  стек поднят: миграции применены, API здоров, worker'ы работают"

for svc in notifications-worker analytics-worker; do
  state="$("${COMPOSE[@]}" ps --format '{{.State}}' "$svc")"
  if [ "$state" = running ]; then
    echo "PASS  $svc работает"
  else
    echo "FAIL  $svc: $state"; fail=1
  fi
done

# Разовые задачи сценария — в контейнере API той же командой compose (shlex-совместимая строка).
JOB_RUNNER="$(printf '%q ' "${COMPOSE[@]}")exec -T backend"
if ! (cd "$ROOT/backend" && E2E_PHONE="$E2E_PHONE" E2E_CODE="$E2E_CODE" \
      poetry run python scripts/e2e_backend.py --base-url "http://127.0.0.1:$PORT" \
      --job-runner "$JOB_RUNNER" | redact); then
  fail=1
fi
# set -o pipefail: код выхода сценария не теряется в пайпе через redact.

# Логи всех сервисов стека не содержат секретов, ключей S3, пароля БД и кода тестового номера.
logs="$("${COMPOSE[@]}" logs --no-color 2>&1)"
leak=none
for value in "$JWT_SECRET" "$SMS_CODE_SECRET" "$S3_SECRET_KEY" "$POSTGRES_PASSWORD"; do
  if grep -qF -- "$value" <<<"$logs"; then leak=found; fi
done
if [ "$leak" = none ]; then
  echo "PASS  логи стека не содержат секретов, ключей S3 и пароля БД"
else
  echo "FAIL  в логах стека найдены секреты"; fail=1
fi

if [ "$fail" -ne 0 ]; then
  show_logs
  exit 1
fi
echo "Интеграционный стек: всё PASS"
