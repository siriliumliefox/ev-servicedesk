#!/usr/bin/env bash
# Правила хранения бакетов S3 Timeweb (глава 26, ADR 0030 п. 10). Запускает владелец — ключи S3 вводятся
# скрыто и передаются aws-cli в контейнере через переменные окружения (не argv).
#
#   scripts/s3-lifecycle.sh <staging|production>
#
# media:  uploads/ — 1 сутки (незакреплённые загрузки, ADR 0017 п. 10); старые версии — 7 дней
#         (privacy-worker удаляет вложения — ПД не переживают срок 99-З в 15 дней).
# backup: старые версии — 1 сутки (ретенцию ведёт pgBackRest). Версионирование Timeweb не отключается.
set -euo pipefail
ENV="${1:-}"
case "$ENV" in staging|production) ;; *) echo "окружение — staging или production" >&2; exit 2 ;; esac
ENDPOINT="${S3_ENDPOINT:-https://s3.twcstorage.ru}"
AWS="amazon/aws-cli:2.32.0@sha256:bb82c6ce5c78cd8aad48d0003ab097c858cda14f9ce389c2345c50cce0104efd"
read -r -p "Имя бакета media [ev-$ENV-media]: " media; media="${media:-ev-$ENV-media}"
read -r -p "Имя бакета backup [ev-$ENV-backup]: " backup; backup="${backup:-ev-$ENV-backup}"
read -r -s -p "Ключ доступа S3: " AWS_ACCESS_KEY_ID; echo
read -r -s -p "Секретный ключ S3: " AWS_SECRET_ACCESS_KEY; echo
export AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY
work="$(mktemp -d)"; trap 'rm -rf "$work"' EXIT
cat > "$work/media.json" <<'JSON'
{"Rules": [
  {"ID": "expire-uploads", "Status": "Enabled", "Filter": {"Prefix": "uploads/"}, "Expiration": {"Days": 1}},
  {"ID": "noncurrent-7d", "Status": "Enabled", "Filter": {"Prefix": ""}, "NoncurrentVersionExpiration": {"NoncurrentDays": 7}}
]}
JSON
cat > "$work/backup.json" <<'JSON'
{"Rules": [
  {"ID": "noncurrent-1d", "Status": "Enabled", "Filter": {"Prefix": ""}, "NoncurrentVersionExpiration": {"NoncurrentDays": 1}}
]}
JSON
aws() { docker run --rm -e AWS_ACCESS_KEY_ID -e AWS_SECRET_ACCESS_KEY -e AWS_DEFAULT_REGION=ru-1 -v "$work:/w:ro" "$AWS" --endpoint-url "$ENDPOINT" "$@"; }
aws s3api put-bucket-lifecycle-configuration --bucket "$media" --lifecycle-configuration file:///w/media.json
aws s3api put-bucket-lifecycle-configuration --bucket "$backup" --lifecycle-configuration file:///w/backup.json
aws s3api get-bucket-lifecycle-configuration --bucket "$media" | grep -c '"ID"' | sed 's/^/правил media: /'
aws s3api get-bucket-lifecycle-configuration --bucket "$backup" | grep -c '"ID"' | sed 's/^/правил backup: /'
# nosniff Timeweb на объекты не ставит (ADR 0030 п. 10, принятый S4) — проверка заголовка для отчёта:
echo "Заголовок X-Content-Type-Options у объекта: проверяется после первой загрузки (docs/runbooks/OWNER_ACTIONS_26.md)."
