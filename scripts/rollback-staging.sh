#!/usr/bin/env bash
# Откат staging на конкретный коммит (Глава 4, шаг 5 — "Проверка отката").
#
# Механизм: cd-staging.yml поддерживает workflow_dispatch с параметром
# git_sha — просто перезапускает деплой для УЖЕ собранного образа
# (ghcr.io/.../backend:staging-<sha>), ничего не собирая заново. Быстрее и
# безопаснее, чем откатывать сам git-репозиторий.
#
# Требование: образ с этим SHA должен существовать в ghcr.io — то есть
# коммит уже проходил через cd-staging.yml раньше (обычный случай при
# откате "на предыдущий рабочий деплой").
#
# Использование:
#   export GITHUB_REPO=owner/ev-servicedesk
#   ./scripts/rollback-staging.sh <git-sha>

set -euo pipefail

: "${GITHUB_REPO:?export GITHUB_REPO=<owner>/<repo>}"
SHA="${1:?Использование: ./scripts/rollback-staging.sh <git-sha>}"

command -v gh >/dev/null || { echo "Нужен GitHub CLI: brew install gh && gh auth login"; exit 1; }

echo "→ Проверяю, что образ для ${SHA} существует в ghcr.io..."
if ! gh api "orgs/${GITHUB_REPO%%/*}/packages/container/$(basename "$GITHUB_REPO")%2Fbackend/versions" \
     --jq ".[].metadata.container.tags[]" 2>/dev/null | grep -q "staging-${SHA}"; then
  echo "  ⚠️  Не нашла тег staging-${SHA} автоматически (может не хватать прав API для чтения пакетов.)"
  echo "     Проверьте вручную: https://github.com/${GITHUB_REPO}/pkgs/container/backend"
  read -r -p "  Продолжить откат всё равно? [y/N] " confirm
  [[ "$confirm" == "y" ]] || exit 1
fi

echo "→ Запускаю cd-staging.yml с git_sha=${SHA}..."
gh workflow run cd-staging.yml --repo "${GITHUB_REPO}" -f git_sha="${SHA}"

echo "Готово. Проследить: gh run watch --repo ${GITHUB_REPO}"
