#!/usr/bin/env bash
# Интеграционный стек backend (Глава 17, ADR 0021 п. 1, 8, 9): все сервисы из ОДНОГО
# образа-кандидата в режиме ENVIRONMENT=staging — миграции, API, worker уведомлений, worker
# аналитики, PostgreSQL, Redis, MinIO (docker-compose.yml + docker-compose.integration.yml,
# отдельный проект: свои тома и сеть, порты PostgreSQL и Redis наружу не публикуются). На стеке —
# сквозной сценарий backend/scripts/e2e_backend.py (каждый ответ сверяется с контрактом) и
# аудит целостности. Секреты, ключи MinIO, пароль БД и код тестового номера — одноразовые
# случайные; передаются через временный файл окружения и нигде не печатаются; логи — через
# redact и проверяются на утечку. Стек удаляется при выходе (тома тоже).
# Нужны: docker compose ≥ 2.24 (!reset), poetry-окружение backend (dev-зависимости).
# Запуск: scripts/integration_stack.sh <образ> [-- команда]   (например backend:smoke)
# Команда после «--» выполняется на том же стеке после сценария backend (глава 18, ADR 0022 п. 2) с окружением:
# API_BASE_URL, E2E_CODE — код тестовых номеров, E2E_JOB_RUNNER — префикс разовой задачи в контейнере API
# (глава 19, ADR 0023 п. 7), E2E_COMPOSE — префикс docker compose стека (разовый контейнер с каталогом тестов,
# ADR 0026 п. 14), и тестовые номера клиентов наборов — CLIENT_PHONES ниже (у каждого набора свой номер, не тот,
# что блокирует сценарий backend).
# Глава 20 (ADR 0024 п. 2, 5): MinIO открыт на INTEGRATION_S3_PORT (19000), presigned URL подписываются
# для INTEGRATION_S3_PUBLIC (по умолчанию http://127.0.0.1:19000; iPhone — http://<mac>.local:19000).
# FCM_SERVICE_ACCOUNT_FILE — JSON-ключ Firebase (scripts/firebase_dev_setup.sh): настоящий push вместо
# фейка; ключ идёт только через файл окружения, логи проверяются на его утечку.

set -euo pipefail

IMAGE="${1:?Укажите образ, например backend:smoke}"
shift
EXTRA=()
if [ "${1:-}" = "--" ]; then
  shift
  EXTRA=("$@")
fi
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PROJECT="ev-integration-$$"
PORT="${INTEGRATION_PORT:-18080}"
S3_PORT="${INTEGRATION_S3_PORT:-19000}"
S3_PUBLIC="${INTEGRATION_S3_PUBLIC:-http://127.0.0.1:$S3_PORT}"
# Тестовые номера: SMS не отправляется, код — E2E_CODE (ADR 0021 п. 6). E2E_PHONE — сценарий backend.
E2E_PHONE="+375290009001"
CLIENT_PHONES=(
  E2E_PHONE=+375290009002           # E2E мобильного клиента (ADR 0022 п. 2)
  E2E_SCHEME_PHONE=+375290009003    # 5 тестовых авто схемы агрегатов (ADR 0023 п. 7)
  E2E_SUPPORT_PHONE=+375290009004   # клиентский сценарий главы 20: дерево → тикет → чат (ADR 0024 п. 1)
  E2E_WEB_PHONE=+375290009005       # клиент веб-кабинета инженера главы 21 (ADR 0025 п. 14)
  E2E_ADMIN_PHONE=+375290009006     # клиент админ-панели главы 22 (ADR 0026 п. 15)
  E2E_SYSTEM_PHONE=+375290009007    # клиент X межролевых сценариев главы 23 (ADR 0027 п. 8)
  E2E_SYSTEM_PHONE_Y=+375290009008  # клиент Y другой модели — таргетинг прошивки (ADR 0027 п. 15)
  E2E_NOTIFY_PHONE=+375290009009    # центр уведомлений: напоминание о ТО и прошивка (ADR 0027 п. 15)
  E2E_ZAP_PHONE=+375290009010       # клиент сканирования OWASP ZAP (глава 25, ADR 0029 п. 7)
)
TEST_PHONES="$E2E_PHONE"
for pair in "${CLIENT_PHONES[@]}"; do TEST_PHONES+=",${pair#*=}"; done

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
SMS_TEST_PHONES=$TEST_PHONES
SMS_TEST_CODE=$E2E_CODE
EOF
# Срок access-токена стенда (глава 25): активный проход ZAP длиннее 15 минут.
if [ -n "${INTEGRATION_ACCESS_TOKEN_TTL:-}" ]; then
  echo "ACCESS_TOKEN_TTL_SECONDS=$INTEGRATION_ACCESS_TOKEN_TTL" >>"$ENV_FILE"
fi
# Фрагмент закрытого ключа Firebase — для проверки логов на утечку (сам ключ не печатается).
FCM_KEY_PART=""
if [ -n "${FCM_SERVICE_ACCOUNT_FILE:-}" ]; then
  FCM_JSON="$(python3 -c 'import json,sys; print(json.dumps(json.load(open(sys.argv[1])), separators=(",", ":")))' \
    "$FCM_SERVICE_ACCOUNT_FILE")"
  FCM_KEY_PART="$(python3 -c 'import json,sys; print(json.loads(sys.stdin.read())["private_key"][40:80])' <<<"$FCM_JSON")"
  printf 'PUSH_PROVIDER=fcm\nFCM_SERVICE_ACCOUNT_JSON=%s\n' "$FCM_JSON" >>"$ENV_FILE"
  unset FCM_JSON
else
  echo "PUSH_PROVIDER=fake" >>"$ENV_FILE"
fi

# Подстановки docker-compose.yml: образ, окружение, файл секретов, ключи MinIO, БД.
export BACKEND_IMAGE="$IMAGE" BACKEND_ENV_FILE="$ENV_FILE" ENVIRONMENT=staging \
  INTEGRATION_PORT="$PORT" INTEGRATION_S3_PORT="$S3_PORT" S3_PUBLIC_ENDPOINT="$S3_PUBLIC" S3_ACCESS_KEY S3_SECRET_KEY S3_BUCKET=ev-servicedesk-integration \
  POSTGRES_USER=integration POSTGRES_PASSWORD POSTGRES_DB=ev_servicedesk_integration
COMPOSE=(docker compose -p "$PROJECT" -f "$ROOT/docker-compose.yml"
         -f "$ROOT/docker-compose.integration.yml")
# Дополнительные файлы compose через пробел — например, нагрузочный стенд главы 24
# (scripts/load_stack.sh, docker-compose.load.yml: ресурсы, прокси-заголовки, эмуляция FCM).
for extra in ${INTEGRATION_EXTRA_COMPOSE:-}; do COMPOSE+=(-f "$extra"); done
COMPOSE+=(--profile full)

# Построчный вывод (BSD sed — -l, GNU — -u): строки команды после «--» видны сразу, а не в конце.
if sed --version >/dev/null 2>&1; then SED_LINE=-u; else SED_LINE=-l; fi
redact() {
  sed "$SED_LINE" -e "s/$JWT_SECRET/***/g" -e "s/$SMS_CODE_SECRET/***/g" -e "s/$S3_SECRET_KEY/***/g" \
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

for svc in notifications-worker analytics-worker privacy-worker; do
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

if [ "${#EXTRA[@]}" -gt 0 ]; then
  if (env API_BASE_URL="http://127.0.0.1:$PORT" E2E_CODE="$E2E_CODE" E2E_JOB_RUNNER="$JOB_RUNNER" \
      E2E_COMPOSE="$(printf '%q ' "${COMPOSE[@]}")" "${CLIENT_PHONES[@]}" \
      "${EXTRA[@]}" 2>&1 | redact); then
    echo "PASS  ${EXTRA[*]}"
  else
    echo "FAIL  ${EXTRA[*]}"; fail=1
  fi
fi

# Логи всех сервисов стека не содержат секретов, ключей S3, пароля БД и кода тестового номера.
logs="$("${COMPOSE[@]}" logs --no-color 2>&1)"
leak=none
for value in "$JWT_SECRET" "$SMS_CODE_SECRET" "$S3_SECRET_KEY" "$POSTGRES_PASSWORD" ${FCM_KEY_PART:+"$FCM_KEY_PART"}; do
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
