#!/usr/bin/env bash
# Откат staging на ранее собранный коммит (Глава 4, ADR 0008).
#
# Механизм: cd-staging.yml с workflow_dispatch и git_sha НЕ пересобирает
# образ, а перетегирует существующий ghcr.io/<repo>/backend:staging-<sha>
# в backend:staging и сверяет digest (PASS/FAIL в логе job
# rollback-backend-image). Откатиться можно только на коммит, который уже
# проходил через cd-staging.yml (образ staging-<sha> существует).
#
# Использование:
#   ./scripts/rollback-staging.sh <git-sha>          # короткий или полный SHA
#   GITHUB_REPO=owner/repo ./scripts/rollback-staging.sh <git-sha>
#
# Проверка существования образа заранее требует у gh scope read:packages
# (gh auth refresh -s read:packages); без него проверку выполнит сам workflow.

set -euo pipefail

command -v gh >/dev/null || { echo "Нужен GitHub CLI: brew install gh && gh auth login"; exit 1; }

REPO="${GITHUB_REPO:-$(gh repo view --json nameWithOwner --jq .nameWithOwner)}"
INPUT="${1:?Использование: ./scripts/rollback-staging.sh <git-sha>}"

SHA=$(gh api "repos/${REPO}/commits/${INPUT}" --jq .sha) || { echo "Коммит ${INPUT} не найден в ${REPO}"; exit 1; }
echo "→ Коммит: ${SHA}"

OWNER="${REPO%%/*}"
PACKAGE="$(basename "$REPO")%2Fbackend"
if [ "$(gh api "users/${OWNER}" --jq .type)" = "Organization" ]; then
  VERSIONS="orgs/${OWNER}/packages/container/${PACKAGE}/versions"
else
  VERSIONS="users/${OWNER}/packages/container/${PACKAGE}/versions"
fi

echo "→ Ищу образ backend:staging-${SHA}..."
if tags=$(gh api --paginate "$VERSIONS" --jq '.[].metadata.container.tags[]' 2>/dev/null); then
  grep -qx "staging-${SHA}" <<<"$tags" || { echo "  Образа backend:staging-${SHA} нет — этот коммит не собирался cd-staging."; exit 1; }
  echo "  найден"
else
  echo "  не удалось прочитать пакеты (нужен scope read:packages) — проверку выполнит workflow"
fi

echo "→ Запускаю cd-staging.yml (ветка develop) с git_sha=${SHA}..."
gh workflow run cd-staging.yml --repo "$REPO" --ref develop -f git_sha="$SHA"
echo "Готово. Проследить: gh run watch --repo ${REPO} \$(gh run list --repo ${REPO} --workflow cd-staging.yml --limit 1 --json databaseId --jq '.[0].databaseId')"
