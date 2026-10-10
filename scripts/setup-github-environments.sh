#!/usr/bin/env bash
# GitHub Environments (Глава 4, ADR 0008): модель local → staging → production.
#
#   staging    — деплой только из develop;
#   production — деплой только из main + required reviewer (PROD_APPROVER).
#
# Environment protection, в отличие от PR-review, допускает одобрение
# собственного деплоя: reviewer на production — реальная пауза перед
# прод-деплоем даже в команде из одного человека. Обход администратором
# выключен (can_admins_bypass=false). Окружения `dev` нет (ADR 0008).
#
# Требует: gh CLI, gh auth login, права admin на репозиторий.
# Запуск:  PROD_APPROVER=<github-логин> ./scripts/setup-github-environments.sh
# Идемпотентен. Секреты — scripts/set-environment-secrets.sh.

set -euo pipefail

command -v gh >/dev/null || { echo "Нужен GitHub CLI: brew install gh && gh auth login"; exit 1; }

REPO="${GITHUB_REPO:-$(gh repo view --json nameWithOwner --jq .nameWithOwner)}"
PROD_APPROVER="${PROD_APPROVER:-$(gh api user --jq .login)}"

# Окружение с единственной разрешённой веткой; лишние политики удаляются.
create_env() {
  local env_name="$1" branch="$2" reviewers="$3"
  echo "→ ${env_name}: только ветка ${branch}"
  gh api -X PUT "repos/${REPO}/environments/${env_name}" --input - >/dev/null <<EOF
{
  "reviewers": ${reviewers},
  "prevent_self_review": false,
  "can_admins_bypass": false,
  "deployment_branch_policy": {"protected_branches": false, "custom_branch_policies": true}
}
EOF
  local base="repos/${REPO}/environments/${env_name}/deployment-branch-policies"
  gh api "$base" --jq '.branch_policies[] | "\(.id) \(.name)"' | while read -r id name; do
    [ "$name" = "$branch" ] || gh api -X DELETE "${base}/${id}"
  done
  gh api "$base" --jq '.branch_policies[].name' | grep -qx "$branch" \
    || gh api -X POST "$base" -f "name=${branch}" -f type=branch >/dev/null
}

approver_id=$(gh api "users/${PROD_APPROVER}" --jq .id)
create_env staging develop '[]'
create_env production main "[{\"type\": \"User\", \"id\": ${approver_id}}]"

if gh api "repos/${REPO}/environments/dev" >/dev/null 2>&1; then
  echo "→ удаляю окружение dev (ADR 0008)"
  gh api -X DELETE "repos/${REPO}/environments/dev"
fi

echo
for env_name in staging production; do
  gh api "repos/${REPO}/environments/${env_name}" --jq '
    "\(.name): admins_bypass=\(.can_admins_bypass) reviewers=\([.protection_rules[] | select(.type=="required_reviewers") | .reviewers[].reviewer.login] | join(","))"'
  echo "  ветки: $(gh api "repos/${REPO}/environments/${env_name}/deployment-branch-policies" --jq '[.branch_policies[].name] | join(",")')"
done
