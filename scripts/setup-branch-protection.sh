#!/usr/bin/env bash
# Настройка branch protection для main/develop через GitHub REST API.
# Требует personal access token с правом `repo` (Settings → Developer settings
# → Fine-grained tokens → Administration: Read & write на нужном репозитории).
#
# Запуск:
#   export GITHUB_TOKEN=ghp_...
#   export GITHUB_REPO=owner/ev-servicedesk
#   ./scripts/setup-branch-protection.sh
#
# Идемпотентен — можно запускать повторно, перезапишет теми же настройками.

set -euo pipefail

: "${GITHUB_TOKEN:?Нужен export GITHUB_TOKEN=<personal access token>}"
: "${GITHUB_REPO:?Нужен export GITHUB_REPO=<owner>/<repo>, например sirilium/ev-servicedesk}"

API="https://api.github.com/repos/${GITHUB_REPO}/branches"

protect() {
  local branch="$1"
  echo "→ Защищаю ветку: ${branch}"
  http_code=$(curl -s -o /tmp/branch_protect_response.json -w "%{http_code}" \
    -X PUT \
    -H "Authorization: Bearer ${GITHUB_TOKEN}" \
    -H "Accept: application/vnd.github+json" \
    "${API}/${branch}/protection" \
    -d '{
      "required_status_checks": null,
      "enforce_admins": false,
      "required_pull_request_reviews": {
        "required_approving_review_count": 0,
        "dismiss_stale_reviews": true
      },
      "restrictions": null,
      "allow_force_pushes": false,
      "allow_deletions": false,
      "required_linear_history": true
    }')
  if [ "$http_code" = "200" ]; then
    echo "  OK — прямой push запрещён, PR обязателен (review не required, см. CONTRIBUTING.md)"
  else
    echo "  ОШИБКА (HTTP ${http_code}):"
    cat /tmp/branch_protect_response.json
    exit 1
  fi
}

protect "main"
protect "develop"

cat << 'EOF'

Готово. Один пункт оставлен на потом намеренно:
required_status_checks сейчас null — CI-джобы (Глава 4, шаг 4) ещё не
существуют, добавить их сюда раньше нечего было бы проверять. После шага 4
дозаполните командой:

  curl -X PATCH \
    -H "Authorization: Bearer $GITHUB_TOKEN" \
    -H "Accept: application/vnd.github+json" \
    "https://api.github.com/repos/$GITHUB_REPO/branches/main/protection/required_status_checks" \
    -d '{"strict": true, "contexts": ["backend-ci", "web-ci", "mobile-ci"]}'

(и аналогично для develop, с именами джобов из .github/workflows/ci.yml)
EOF
