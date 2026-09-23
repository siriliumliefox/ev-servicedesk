#!/usr/bin/env bash
# Создаёт GitHub Environments (dev/staging/production) с разделёнными
# секретами и веткой-ограничением деплоя (Глава 4, шаг 3).
#
# В отличие от PR-ревью (CONTRIBUTING.md — там self-approve запрещён
# GitHub'ом в принципе), Environment protection ЭТО позволяет: можно
# назначить самого себя required reviewer на production — реальный
# "стоп-кран" перед прод-деплоем, а не фикция, даже соло.
#
# Требует: gh CLI (`brew install gh` на macOS), gh auth login,
# права admin на репозиторий.
#
# Запуск:
#   export GITHUB_REPO=owner/ev-servicedesk
#   export PROD_APPROVER=your-github-handle   # обычно — вы сами
#   ./scripts/setup-github-environments.sh

set -euo pipefail

: "${GITHUB_REPO:?export GITHUB_REPO=<owner>/<repo>}"
: "${PROD_APPROVER:?export PROD_APPROVER=<github-логин, обычно ваш>}"

command -v gh >/dev/null || { echo "Нужен GitHub CLI: brew install gh && gh auth login"; exit 1; }

create_env() {
  local env_name="$1"
  local branch_pattern="$2"
  echo "→ Создаю окружение: ${env_name} (деплой только из веток: ${branch_pattern})"
  gh api -X PUT "repos/${GITHUB_REPO}/environments/${env_name}" \
    -f "deployment_branch_policy[protected_branches]=false" \
    -f "deployment_branch_policy[custom_branch_policies]=true" >/dev/null
  gh api -X POST "repos/${GITHUB_REPO}/environments/${env_name}/deployment-branch-policies" \
    -f "name=${branch_pattern}" >/dev/null 2>&1 || true
}

create_env "dev" "develop"
create_env "staging" "develop"
create_env "production" "main"

echo "→ Назначаю required reviewer на production: ${PROD_APPROVER}"
reviewer_id=$(gh api "users/${PROD_APPROVER}" --jq '.id')
gh api -X PUT "repos/${GITHUB_REPO}/environments/production" \
  -f "reviewers[][type]=User" \
  -F "reviewers[][id]=${reviewer_id}" >/dev/null

cat << 'EOF'

Готово. Секреты в каждое окружение — по одному на переменную из .env.example:
  gh secret set DATABASE_URL --env dev
  gh secret set JWT_SECRET --env dev
  ... (повторить для staging, production — значения РАЗНЫЕ на каждое окружение,
       генерировать через scripts/generate-secret.sh, не переиспользовать)

Проверка: gh api repos/$GITHUB_REPO/environments — production должен
показывать protection_rules с вашим reviewer.
EOF
