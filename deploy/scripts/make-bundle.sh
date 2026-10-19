#!/usr/bin/env bash
# Bundle деплоя (глава 26, ADR 0030 п. 7): один tar.gz в stdin `ssh deploy@<ВМ> deploy <env>`.
#
#   make-bundle.sh <env> <выход.tar.gz>
#
# Переменные: EV_SHA (40 hex), BACKEND_IMAGE (…@sha256:…), EV_POSTGRES_IMAGE, WEB_ENGINEER_DIST,
# WEB_ADMIN_DIST (каталоги сборки), EV_OVERRIDES_FILE (необязательно: переменные окружения GitHub),
# GHCR_TOKEN и GHCR_USER (необязательно: временный токен pull), секреты — как в render-secrets.sh.
# deploy/ берётся из каталога скрипта: конфигурации того же коммита, что и образ.
set -euo pipefail
export COPYFILE_DISABLE=1   # bsdtar на Mac не добавляет ._-файлы расширенных атрибутов
ENV="${1:?окружение}"
OUT="${2:?файл bundle}"
SRC="$(cd "$(dirname "$0")/.." && pwd)"
[[ "${EV_SHA:-}" =~ ^[0-9a-f]{40}$ ]] || { echo "EV_SHA — полный SHA" >&2; exit 2; }
[[ "${BACKEND_IMAGE:-}" == *@sha256:* ]] || { echo "BACKEND_IMAGE — образ по digest (…@sha256:…)" >&2; exit 2; }
: "${EV_POSTGRES_IMAGE:?}" "${WEB_ENGINEER_DIST:?}" "${WEB_ADMIN_DIST:?}"
[[ -f "$WEB_ENGINEER_DIST/index.html" && -f "$WEB_ADMIN_DIST/index.html" ]] || { echo "нет сборки кабинетов" >&2; exit 2; }

work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT
release="$work/release"
mkdir -p "$release/web"
# deploy/ без локальных артефактов (rendered/ создаёт deploy.sh на ВМ).
tar -C "$SRC/.." --exclude 'deploy/rendered' --exclude '__pycache__' -cf - deploy | tar -C "$release" -xf -
cp -R "$WEB_ENGINEER_DIST" "$release/web/web-engineer"
cp -R "$WEB_ADMIN_DIST" "$release/web/web-admin"
# Конфигурации — читаемые (контейнеры Prometheus, Grafana, Loki работают не от root; на ВМ их
# закрывает каталог окружения 0750); секреты — только владелец (render-secrets.sh: umask 077).
"$SRC/scripts/render-secrets.sh" "$ENV" "$release/secrets"
{
  printf 'EV_SHA=%s\n' "$EV_SHA"
  printf 'BACKEND_IMAGE=%s\n' "$BACKEND_IMAGE"
  printf 'EV_POSTGRES_IMAGE=%s\n' "$EV_POSTGRES_IMAGE"
  printf 'GHCR_USER=%s\n' "${GHCR_USER:-deploy}"
} > "$release/meta.env"
if [[ -n "${EV_OVERRIDES_FILE:-}" ]]; then cp "$EV_OVERRIDES_FILE" "$release/overrides.env"; else : > "$release/overrides.env"; fi
if [[ -n "${GHCR_TOKEN:-}" ]]; then (umask 077 && printf '%s' "$GHCR_TOKEN" > "$release/ghcr_token"); fi
tar -C "$work" -czf "$OUT" release
