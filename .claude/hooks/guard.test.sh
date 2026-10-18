#!/usr/bin/env bash
# Проверка .claude/hooks/guard.sh на тестовых JSON-входах: каждое правило срабатывает, обычные операции проходят.
# Запуск: .claude/hooks/guard.test.sh            (таблица Markdown в stdout, код возврата 1 при расхождении)
#         /bin/bash .claude/hooks/guard.test.sh  (системный bash 3.2 macOS)
# Нужны: jq, git.

set -u
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
GUARD="$HERE/guard.sh"

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
# Два временных репозитория: на защищённой ветке develop и на feature-ветке — для push без refspec.
for pair in "dev:develop" "feat:feature/x"; do
    dir="$TMP/${pair%%:*}"
    mkdir -p "$dir"
    git -C "$dir" init -q -b "${pair##*:}"
    git -C "$dir" -c user.name=t -c user.email=t@t.invalid commit -q --allow-empty -m init
done
DEV="$TMP/dev"
FEAT="$TMP/feat"

failed=0
n=0
echo "| № | Инструмент | Вход | Ожидалось | Получено | |"
echo "|--:|---|---|---|---|---|"

# check <ожидание: allow|deny|ask> <инструмент> <команда или путь> [cwd]
check() {
    local expect=$1 tool=$2 arg=$3 cwd=${4:-$FEAT} json got shown
    case "$tool" in
        Bash) json=$(jq -n --arg t "$tool" --arg a "$arg" --arg c "$cwd" '{tool_name: $t, cwd: $c, tool_input: {command: $a}}') ;;
        Grep) json=$(jq -n --arg t "$tool" --arg a "$arg" --arg c "$cwd" '{tool_name: $t, cwd: $c, tool_input: {pattern: "x", path: $a}}') ;;
        *) json=$(jq -n --arg t "$tool" --arg a "$arg" --arg c "$cwd" '{tool_name: $t, cwd: $c, tool_input: {file_path: $a}}') ;;
    esac
    got=$(printf '%s' "$json" | "$GUARD" | jq -r '.hookSpecificOutput.permissionDecision // empty')
    [ -n "$got" ] || got=allow
    n=$((n + 1))
    shown=${arg//$'\n'/ ⏎ }
    shown=${shown//|/\\|}
    shown=${shown//$TMP/<tmp>}
    local mark="✅"
    if [ "$got" != "$expect" ]; then
        mark="❌"
        failed=$((failed + 1))
    fi
    local where=""
    [ "$cwd" = "$DEV" ] && where=" (cwd на ветке develop)"
    echo "| $n | $tool | \`${shown}\`$where | $expect | $got | $mark |"
}

# --- deny: --no-verify и обход хуков ---
check deny Bash 'git commit --no-verify -m "fix"'
check deny Bash 'git commit -n -m fix'
check deny Bash 'git commit -nm "fix"'
check deny Bash 'git add -A && git commit -a --no-verify -m "wip"'
check deny Bash 'git push --no-verify origin feature/x'
check deny Bash 'git -c core.hooksPath=/dev/null commit -m fix'
# --- deny: push в main/develop ---
check deny Bash 'git push origin develop'
check deny Bash 'git push origin main'
check deny Bash 'git push -u origin HEAD:develop'
check deny Bash 'git push origin +HEAD:refs/heads/main'
check deny Bash 'git push origin :develop'
check deny Bash 'git push --force origin develop'
check deny Bash 'git push --all'
check deny Bash 'git push' "$DEV"
check deny Bash 'git push origin HEAD' "$DEV"
check deny Bash "git -C $DEV push"
check deny Bash "cd $DEV && git push origin"
# --- deny: .env ---
check deny Bash 'cat .env'
check deny Bash 'cat backend/.env'
check deny Bash 'source .env'
# shellcheck disable=SC2016
check deny Bash 'grep SECRET "$ROOT/.env"'
check deny Bash 'head -3 ./.env.production'
check deny Bash 'docker compose --env-file .env config'
check deny Bash 'echo ok && cat .env'
check deny Read '/Users/dev/ev-servicedesk/.env'
check deny Read '/Users/dev/ev-servicedesk/backend/.env.local'
check deny Edit '.env'
check deny Write '.env.production'
check deny Grep '/Users/dev/ev-servicedesk/.env'
# --- deny: генерируемые файлы ---
check deny Edit 'web-shared/src/api/schema.ts'
check deny Write '/Users/dev/ev-servicedesk/web-shared/src/theme/tokens.css'
check deny Edit 'mobile/lib/theme/tokens.g.dart'
check deny Edit 'docs/EV_ServiceDesk_Glava2_DDL.sql'
check deny Write '/Users/dev/ev-servicedesk/docs/ERD_EV_ServiceDesk_Glava2.mermaid'
# --- ask ---
check ask Bash 'ssh deploy@example.com uptime'
check ask Bash 'scp build.tar.gz deploy@example.com:/srv'
check ask Bash 'bash scripts/set-a1-secrets.sh'
check ask Bash './scripts/set-fcm-secret.sh'
check ask Bash 'scripts/set-environment-secrets.sh staging'
check ask Bash './scripts/rollback-staging.sh'
check ask Bash 'gh secret set JWT_SECRET --env staging'
check ask Bash 'scripts/generate-secret.sh'
check ask Bash 'scripts/setup-branch-protection.sh'
check ask Edit 'docs/EV_ServiceDesk_SwaggerUI.html'
check ask Edit 'package-lock.json'
check ask Write '/Users/dev/ev-servicedesk/backend/poetry.lock'
check ask Edit 'mobile/pubspec.lock'
# --- allow: обычная работа ---
check allow Bash 'git push -u origin feature/138-production-infra'
check allow Bash 'git push origin chore/claude-automation'
check allow Bash 'git push' "$FEAT"
check allow Bash 'git push origin HEAD' "$FEAT"
check allow Bash 'git push origin feature/x:feature/x'
check allow Bash 'git push origin refs/heads/feature/x'
check allow Bash 'git push origin develop-fix'
check allow Bash 'git push origin release/develop'
check allow Bash "git -C $FEAT push" "$DEV"
check allow Bash 'git pull origin develop'
check allow Bash 'git fetch origin develop && git merge origin/develop'
check allow Bash 'git checkout develop'
check allow Bash 'git commit -am "feat: x"'
check allow Bash 'git commit -mnew'
check allow Bash 'git commit -m "docs: больше не используем --no-verify, не читаем .env и не делаем git push origin develop"'
check allow Bash $'git commit -m "$(cat <<\'EOF\'\nfix: ssh, gh secret set X, git push origin develop, cat .env, --no-verify\n\nCo-Authored-By: Claude\nEOF\n)"'
check allow Bash $'gh pr create --base develop --title "chore: x" --body "$(cat <<\'EOF\'\nPush в develop только через PR; .env не читать; ssh deploy@host\nEOF\n)"'
check allow Bash 'gh pr merge 140 --squash --delete-branch'
check allow Bash 'gh pr view 140 --json statusCheckRollup'
check allow Bash 'gh run list --workflow ci.yml'
check allow Bash 'cat .env.example'
check allow Bash 'git log --oneline -- .env.example'
check allow Bash 'docker compose --env-file .env.example config -q'
check allow Bash 'docker compose up -d'
check allow Bash 'npm run gen:api'
check allow Bash 'npm run tokens'
check allow Bash 'python3 scripts/sync_swagger_html.py'
check allow Bash '(cd backend && poetry run python scripts/export_ddl.py && poetry run python scripts/export_erd.py)'
check allow Bash 'git diff --cached --stat'
check allow Bash 'gitleaks git --pre-commit --staged --redact'
check allow Bash 'ssh-keygen -lf key.pub'
check allow Bash 'grep -rn "\.env" docs | head'
check allow Read '/Users/dev/ev-servicedesk/.env.example'
check allow Read '/Users/dev/ev-servicedesk/AGENTS.md'
check allow Edit '/Users/dev/ev-servicedesk/web-shared/src/api/client.ts'
check allow Edit 'docs/openapi.yaml'
check allow Write 'backend/app/main.py'
check allow Grep '/Users/dev/ev-servicedesk/backend'
check allow WebFetch 'https://example.com'

echo
if [ "$failed" -eq 0 ]; then
    echo "Итого: $n проверок, расхождений нет."
else
    echo "Итого: $n проверок, расхождений: $failed."
    exit 1
fi
