#!/usr/bin/env bash
# Скилл chapter-release, шаг 4: доказательства cd-staging для коммита develop.
# Только чтение: находит прогон cd-staging по SHA, печатает jobs, итог smoke образа,
# интеграционного стека и digest опубликованного backend:staging-<sha>.
#
# Использование (из корня клона): staging_evidence.sh <sha merge-коммита главы>
# Совместим с bash 3.2 (macOS).
set -euo pipefail

cd "$(git rev-parse --show-toplevel)"
git fetch -q origin
sha=$(git rev-parse "${1:?Использование: staging_evidence.sh <sha>}^{commit}")
short=${sha:0:7}

git merge-base --is-ancestor "$sha" origin/develop \
  || { echo "STOP  $short не в origin/develop — cd-staging запускается только из develop"; exit 1; }

runs=$(gh run list --workflow cd-staging.yml --commit "$sha" --limit 10 \
  --json databaseId,status,conclusion,event,url)
if [ "$(jq length <<<"$runs")" -eq 0 ]; then
  # Те же пути, что в on.push.paths cd-staging.yml.
  if git diff-tree --no-commit-id --name-only -r "$sha" | grep -qE \
    '^(backend|web-engineer|web-admin|web-shared|mobile|system-e2e)/|^docker-compose(\.integration)?\.yml$|^scripts/(smoke_backend_image|integration_stack)\.sh$|^\.github/workflows/(cd-staging|regression|web-e2e|mobile-e2e|mobile-ui-e2e)\.yml$'; then
    echo "WARN  прогона cd-staging для $short пока нет, хотя пути затронуты — подождать минуту и повторить"
  else
    echo "OK    cd-staging для $short не запускается: коммит не трогает пути workflow."
    echo "      В статус: «cd-staging не требуется — изменения вне путей cd-staging.yml»."
  fi
  exit 0
fi

# Последний прогон по этому коммиту (повторный запуск после флейка — тот же id, новая попытка).
run=$(jq -r '.[0].databaseId' <<<"$runs")
status=$(jq -r '.[0].status' <<<"$runs")
conclusion=$(jq -r '.[0].conclusion' <<<"$runs")
echo "== cd-staging $run ($short): $status ${conclusion:-}"
echo "   $(jq -r '.[0].url' <<<"$runs")"
jobs=$(gh run view "$run" --json jobs)
jq -r '.jobs[] | "   \(if .conclusion == "" then .status else .conclusion end)\t\(.name)"' <<<"$jobs"

if [ "$status" != completed ]; then
  echo "WARN  прогон не завершён — ждать: gh run watch $run --exit-status (в фоне), затем повторить"
  exit 0
fi
if [ "$conclusion" != success ]; then
  echo "STOP  cd-staging $conclusion — глава не DONE. Упавшие jobs: gh run view $run --log-failed"
  echo "      Флейк regression (известен android-ui-e2e) — один раз: gh run rerun $run --failed"
  exit 1
fi

job=$(jq -r '.jobs[] | select(.name=="build-backend-image") | .databaseId' <<<"$jobs")
regression=$(jq -r '.jobs[] | select(.name=="regression / summary") | .conclusion' <<<"$jobs")
[ -n "$job" ] || { echo "OK    cd-staging $run — success (job build-backend-image не найден: откат?)"; exit 0; }
log=$(gh run view --job "$job" --log)

# Граница: последняя проверка smoke_backend_image.sh — «логи контейнеров не содержат секретов…».
checks=$(grep -E 'Z (PASS|FAIL)  ' <<<"$log" | sed -E 's/.*Z (PASS|FAIL)  /\1  /')
cut_at=$(grep -n 'логи контейнеров не содержат' <<<"$checks" | tail -1 | cut -d: -f1 || true)
if [ -n "$cut_at" ]; then
  smoke=$(head -n "$cut_at" <<<"$checks"); stack=$(tail -n "+$((cut_at + 1))" <<<"$checks")
else
  smoke=$checks; stack=""
fi
count() { grep -c "^$1" <<<"$2" || true; }
sp=$(count PASS "$smoke"); sf=$(count FAIL "$smoke")
tp=$(count PASS "$stack"); tf=$(count FAIL "$stack")
verdict=$(grep -oE 'Интеграционный стек: .*' <<<"$log" | tail -1 || true)
digest=$(grep -oE "backend:staging-$sha@sha256:[0-9a-f]{64}" <<<"$log" | head -1 | sed 's/.*@//' || true)

echo "== Образ backend:staging-$short"
echo "   smoke образа: $sp PASS / $sf FAIL"
echo "   интеграционный стек: $tp PASS / $tf FAIL${verdict:+ (${verdict})}"
echo "   digest: ${digest:-не найден в логе}"
echo
echo "Для status-PR: cd-staging \`$run\` — success (smoke $sp/$((sp + sf)), интеграционный стек PASS, regression ${regression:-не запускался}, digest \`${digest:0:15}…\`)"
