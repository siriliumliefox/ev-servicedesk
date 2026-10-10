#!/usr/bin/env bash
# Branch protection для main и develop (Глава 4, ADR 0008).
#
# Правила (распространяются и на администраторов — enforce_admins):
#   • изменения только через PR, прямой push запрещён;
#   • обязательная проверка — `ci-gate` из ci.yml (только от GitHub Actions,
#     app_id 15368), ветка PR должна быть актуальной относительно базовой;
#   • линейная история, без force-push и удаления ветки;
#   • approve второго человека не требуется (команда из одного человека,
#     см. CONTRIBUTING.md) — при появлении ревьюера поднять REVIEWS до 1.
#
# Требует: gh CLI, gh auth login, права admin на репозиторий.
# Запуск:  ./scripts/setup-branch-protection.sh   (GITHUB_REPO — по умолчанию текущий)
# Идемпотентен.

set -euo pipefail

command -v gh >/dev/null || { echo "Нужен GitHub CLI: brew install gh && gh auth login"; exit 1; }

REPO="${GITHUB_REPO:-$(gh repo view --json nameWithOwner --jq .nameWithOwner)}"
REVIEWS="${REVIEWS:-0}"
GITHUB_ACTIONS_APP_ID=15368

protect() {
  local branch="$1"
  echo "→ ${REPO}: защищаю ${branch}"
  gh api -X PUT "repos/${REPO}/branches/${branch}/protection" --input - >/dev/null <<EOF
{
  "required_status_checks": {
    "strict": true,
    "checks": [{"context": "ci-gate", "app_id": ${GITHUB_ACTIONS_APP_ID}}]
  },
  "enforce_admins": true,
  "required_pull_request_reviews": {
    "required_approving_review_count": ${REVIEWS},
    "dismiss_stale_reviews": true
  },
  "restrictions": null,
  "required_linear_history": true,
  "allow_force_pushes": false,
  "allow_deletions": false
}
EOF
  gh api "repos/${REPO}/branches/${branch}/protection" --jq '
    "  checks=\([.required_status_checks.checks[].context] | join(",")) strict=\(.required_status_checks.strict)"
    + " enforce_admins=\(.enforce_admins.enabled) reviews=\(.required_pull_request_reviews.required_approving_review_count)"
    + " linear=\(.required_linear_history.enabled) force_push=\(.allow_force_pushes.enabled) deletions=\(.allow_deletions.enabled)"'
}

protect main
protect develop
