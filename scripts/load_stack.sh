#!/usr/bin/env bash
# Нагрузочный стенд главы 24 (ADR 0028 п. 5): интеграционный стек из образа-кандидата
# (scripts/integration_stack.sh — режим staging, одноразовые секреты, проверка логов на утечку,
# удаление стека) плюс docker-compose.load.yml (ресурсы будущего сервера, прокси-заголовки,
# эмуляция FCM, pg_stat_statements). На стеке — сид и сценарии k6 (load/run.sh).
#
#   docker build -t backend:load backend
#   scripts/load_stack.sh backend:load per-op            # замер по операциям
#   scripts/load_stack.sh backend:load mixed peak        # несколько сценариев на одном стеке
#
# Сценарии — файлы load/scenarios/<имя>.js. Результаты — load/results/<время>-<сценарий>/ (вне git).
# Порты по умолчанию не пересекаются с другими стендами (18080/19000, 18280/19200).
# LOAD_PROFILE=ci — облегчённый профиль (50 пользователей, 3 мин), LOAD_CLIENTS — число клиентов сида.

set -euo pipefail

IMAGE="${1:?Укажите образ, например backend:load}"
shift
[ "$#" -gt 0 ] || { echo "Укажите сценарий: per-op, mixed, peak, soak" >&2; exit 2; }
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# Presigned URL подписываются для адреса MinIO в сети стека: туда загружает k6 (Q19).
export INTEGRATION_EXTRA_COMPOSE="$ROOT/docker-compose.load.yml" \
  INTEGRATION_S3_PUBLIC="http://minio:9000" \
  INTEGRATION_PORT="${LOAD_PORT:-18380}" \
  INTEGRATION_S3_PORT="${LOAD_S3_PORT:-19300}"
exec "$ROOT/scripts/integration_stack.sh" "$IMAGE" -- "$ROOT/load/run.sh" "$@"
