#!/usr/bin/env bash
# Выкладка и откат окружения на ВМ (глава 26, ADR 0030 пп. 7, 16).
#
#   deploy.sh receive  <env>        — bundle (tar.gz) из stdin: выпуск, секреты, статика, образы; затем release
#   deploy.sh release  <env> <sha>  — включить выпуск: миграции → up → smoke; провал — автооткат
#   deploy.sh rollback <env> [sha]  — на предыдущий (или указанный) выпуск без миграций
#   deploy.sh status   <env>
#
# Запускается через SSH forced command (ev-ssh) от пользователя deploy, на стенде — напрямую.
# Bundle (cd-staging / cd-production, scripts/infra_stack.sh): release/meta.env (EV_SHA, BACKEND_IMAGE,
# EV_POSTGRES_IMAGE), release/overrides.env, release/deploy/, release/web/<app>/, release/secrets/,
# необязательный release/ghcr_token (временный GITHUB_TOKEN job'а — только на время pull).
#
# План отката (ADR 0030 п. 16): миграции совместимы с предыдущим выпуском — откат меняет образ и
# статику, схема остаётся; несовместимая миграция — downgrade вручную или PITR (docs/runbooks/ROLLBACK.md).
set -euo pipefail
# shellcheck source=lib.sh
. "$(cd "$(dirname "$0")" && pwd)/lib.sh"

usage() { sed -n '2,8p' "$0" >&2; exit 2; }

pull_images() {
  local env="$1" dir="$2" token_file="$3"
  load_release_env "$env" "$dir"
  local registry="${BACKEND_IMAGE%%/*}"
  if [[ -s "$token_file" ]]; then
    docker login "$registry" -u "${GHCR_USER:-deploy}" --password-stdin < "$token_file" >/dev/null
  fi
  local status=0
  dc "$env" "$dir" pull --quiet || status=$?
  if [[ -s "$token_file" ]]; then docker logout "$registry" >/dev/null 2>&1 || true; fi
  rm -f "$token_file"
  return "$status"
}

receive() {
  local env="$1"
  local home tmp sha dir app
  home="$(ev_home "$env")"
  mkdir -p "$home/releases" "$home/secrets" "$home/web" "$home/certs" "$home/acme"
  tmp="$(mktemp -d "$home/.receive.XXXXXX")"
  RECEIVE_TMP="$tmp"
  trap 'rm -rf "${RECEIVE_TMP:-}"' EXIT
  tar -xzf - -C "$tmp" --no-same-owner
  [[ -f "$tmp/release/meta.env" ]] || die "в bundle нет release/meta.env"
  sha="$(sed -n 's/^EV_SHA=//p' "$tmp/release/meta.env")"
  check_sha "$sha"
  log "получен выпуск $sha"

  # Секреты — текущие для окружения (откат использует их же): только владелец, 0600. Обновляются на
  # месте (rsync --delete), не подменой каталога: работающие контейнеры смонтировали его каталоги.
  if [[ -d "$tmp/release/secrets" ]]; then
    local new="$tmp/release/secrets"
    find "$new" -type d -exec chmod 0700 {} + && find "$new" -type f -exec chmod 0600 {} +
    # Файлы Alertmanager читает его процесс (nobody) через монтирование каталога: 0755/0644 — их
    # закрывает каталог окружения (0750, пользователь deploy).
    if [[ -d "$new/alertmanager" ]]; then
      chmod 0755 "$new/alertmanager"
      find "$new/alertmanager" -type f -exec chmod 0644 {} +
    fi
    mkdir -p "$home/secrets/alertmanager" && chmod 0700 "$home/secrets"
    rsync -a --delete "$new/" "$home/secrets/"
    rm -rf "$new"
  fi
  for app in web-engineer web-admin; do
    if [[ -d "$tmp/release/web/$app" ]]; then
      mkdir -p "$home/web/$app"
      rm -rf "$home/web/$app/$sha"
      mv "$tmp/release/web/$app" "$home/web/$app/$sha"
    fi
  done
  local token="$home/.ghcr_token"
  rm -f "$token"
  [[ -f "$tmp/release/ghcr_token" ]] && mv "$tmp/release/ghcr_token" "$token" && chmod 0600 "$token"
  rm -rf "$tmp/release/web" "$tmp/release/ghcr_token"

  dir="$home/releases/$sha"
  rm -rf "$dir"
  mv "$tmp/release" "$dir"
  rm -rf "$tmp"
  pull_images "$env" "$dir" "$token"
  if [[ "${EV_RECEIVE_ONLY:-}" == 1 ]]; then
    log "выпуск $sha получен без включения (восстановление — restore.sh)"
    return 0
  fi
  release "$env" "$sha"
}

# activate <env> <dir> <sha> — symlink current и статика на выпуск, up, ожидание health, smoke.
activate() {
  local env="$1" dir="$2" sha="$3" home app
  home="$(ev_home "$env")"
  render_configs "$env" "$dir"
  dc "$env" "$dir" config -q
  for app in web-engineer web-admin; do
    [[ -d "$home/web/$app/$sha" ]] || die "нет статики $app для выпуска $sha"
    ln -sfn "$sha" "$home/web/$app/current"
  done
  ln -sfn "releases/$sha" "$home/current"
  dc "$env" "$dir" up -d --remove-orphans >/dev/null
  wait_healthy "$env" "$dir" backend 180 && wait_healthy "$env" "$dir" nginx 60 && smoke
}

release() {
  local env="$1" sha="$2" home dir prev_sha=""
  check_sha "$sha"
  home="$(ev_home "$env")"
  dir="$(release_dir "$env" "$sha")" || die "нет выпуска $sha"
  if [[ -L "$home/current" ]]; then
    prev_sha="$(basename "$(release_dir "$env" current)")"
  fi
  load_release_env "$env" "$dir"
  log "выпуск $sha (было: ${prev_sha:-нет}), backend ${BACKEND_IMAGE}"

  # Миграции — до переключения: провал не трогает работающий выпуск (DDL PostgreSQL в транзакции).
  render_configs "$env" "$dir"
  dc "$env" "$dir" up -d --wait postgres redis >/dev/null
  dc "$env" "$dir" run --rm --no-deps migrate >/dev/null || die "миграции не прошли — выпуск $sha не включён"

  if activate "$env" "$dir" "$sha"; then
    # Повторная выкладка того же sha не меняет предыдущий выпуск.
    if [[ -n "$prev_sha" && "$prev_sha" != "$sha" ]]; then ln -sfn "releases/$prev_sha" "$home/previous"; fi
    local previous=""
    [[ -L "$home/previous" ]] && previous="$(basename "$(release_dir "$env" previous)")"
    printf 'EV_SHA=%s\nDEPLOYED_AT=%s\nPREVIOUS=%s\n' "$sha" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$previous" > "$home/state"
    "$(dirname "$0")/backup.sh" init "$env" || log "предупреждение: stanza pgBackRest не готова (backup.sh init)"
    install_scripts "$dir"
    prune "$env"
    log "PASS выпуск $sha включён"
    return 0
  fi

  log "FAIL выпуск $sha: health или smoke не прошли"
  if [[ -z "$prev_sha" || "$prev_sha" == "$sha" ]]; then
    die "откатываться не на что (первый выпуск окружения)"
  fi
  log "автооткат на $prev_sha"
  if activate "$env" "$(release_dir "$env" "$prev_sha")" "$prev_sha"; then
    log "автооткат выполнен: работает $prev_sha"
  else
    log "ОШИБКА: автооткат на $prev_sha тоже не прошёл smoke — нужен ручной разбор (docs/runbooks/ROLLBACK.md)"
  fi
  exit 1
}

rollback() {
  local env="$1" target="${2:-}" home current_sha dir
  home="$(ev_home "$env")"
  current_sha="$(basename "$(release_dir "$env" current)")" || die "нет текущего выпуска"
  if [[ -z "$target" ]]; then
    [[ -L "$home/previous" ]] || die "нет предыдущего выпуска"
    target="$(basename "$(release_dir "$env" previous)")"
  fi
  check_sha "$target"
  dir="$(release_dir "$env" "$target")" || die "нет выпуска $target (хранятся последние $KEEP_RELEASES)"
  log "откат $current_sha → $target (без миграций: схема совместима с предыдущим выпуском)"
  activate "$env" "$dir" "$target" || die "откат на $target не прошёл smoke"
  ln -sfn "releases/$current_sha" "$home/previous"
  printf 'EV_SHA=%s\nDEPLOYED_AT=%s\nPREVIOUS=%s\nROLLBACK_FROM=%s\n' \
    "$target" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$current_sha" "$current_sha" > "$home/state"
  log "PASS откат на $target"
}

# install_scripts — скрипты включённого выпуска становятся скриптами ВМ (EV_ROOT/bin): ev-ssh,
# таймеры бэкапа и следующий деплой работают версией из git этого выпуска.
install_scripts() {
  local dir="$1" bin="$EV_ROOT/bin" file
  [[ -d "$bin" && -w "$bin" ]] || return 0
  for file in lib.sh deploy.sh backup.sh restore.sh render.py ev-ssh; do
    install -m 0755 "$dir/deploy/scripts/$file" "$bin/$file.new" && mv "$bin/$file.new" "$bin/$file"
  done
}

# prune — оставить последние выпуски и статику; current и previous не удаляются.
prune() {
  local env="$1" home keep_current keep_previous entry app
  home="$(ev_home "$env")"
  keep_current="$(basename "$(release_dir "$env" current 2>/dev/null || echo none)")"
  keep_previous="$(basename "$(release_dir "$env" previous 2>/dev/null || echo none)")"
  # Имена выпусков — sha, без пробелов: ls безопасен.
  # shellcheck disable=SC2012
  for entry in $(ls -1t "$home/releases" | tail -n +$((KEEP_RELEASES + 1))); do
    [[ "$entry" == "$keep_current" || "$entry" == "$keep_previous" ]] && continue
    rm -rf "${home:?}/releases/$entry"
    for app in web-engineer web-admin; do rm -rf "${home:?}/web/$app/$entry"; done
  done
}

status() {
  local env="$1" home
  home="$(ev_home "$env")"
  [[ -f "$home/state" ]] && cat "$home/state" || echo "окружение $env ещё не выкладывалось"
}

main() {
  local command="${1:-}"
  [[ $# -ge 2 ]] || usage
  check_env_name "$2"
  case "$command" in
    receive) receive "$2" ;;
    release) [[ $# -eq 3 ]] || usage; release "$2" "$3" ;;
    rollback) rollback "$2" "${3:-}" ;;
    status) status "$2" ;;
    *) usage ;;
  esac
}

main "$@"
