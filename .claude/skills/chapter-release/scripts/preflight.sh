#!/usr/bin/env bash
# Скилл chapter-release, шаги 1–2: готов ли PR главы к merge и что потребуется дальше.
# Только чтение: ничего не мержит, не тегирует, не пушит (годится для сухого прогона).
#
# Использование (из корня клона): preflight.sh <номер PR главы> [номер главы]
# Номер главы берётся из заголовка PR («Глава 25: …», «feat(22): …»), если не передан.
# Вывод: строки OK / WARN / STOP и итог. STOP — merge нельзя, решает владелец или нужна доработка.
# Совместим с bash 3.2 (macOS).
set -euo pipefail

pr="${1:?Использование: preflight.sh <PR главы> [глава]}"
chapter="${2:-}"
cd "$(git rev-parse --show-toplevel)"
git fetch -q origin --tags --prune

stops=0
ok()   { printf 'OK    %s\n' "$*"; }
warn() { printf 'WARN  %s\n' "$*"; }
stop() { printf 'STOP  %s\n' "$*"; stops=$((stops + 1)); }
info() { printf '      %s\n' "$*"; }

json=$(gh pr view "$pr" --json number,title,state,isDraft,baseRefName,headRefName,mergeStateStatus,mergeCommit,closingIssuesReferences,body,files)
f() { jq -r "$1" <<<"$json"; }

title=$(f .title); state=$(f .state); head=$(f .headRefName); base=$(f .baseRefName)
echo "== PR #$pr: $title"
info "ветка $head → $base, состояние $state, draft=$(f .isDraft), mergeState=$(f .mergeStateStatus)"

if [ -z "$chapter" ]; then
  chapter=$(sed -nE 's/^Глава ([0-9]+).*/\1/p; s/^[a-z]+\(([0-9]+)\).*/\1/p' <<<"$title" | head -1)
fi
[ -n "$chapter" ] || { stop "номер главы не найден в заголовке — передайте вторым аргументом"; exit 0; }
nn=$(printf '%02d' "$((10#$chapter))")
info "глава $nn"

if [ "$base" = develop ]; then ok "база PR — develop"; else stop "база PR — $base, а глава мержится в develop"; fi

# Где читать документы главы: смерженный PR — по squash-коммиту, открытый — по голове ветки.
case "$state" in
  MERGED) ref=$(f .mergeCommit.oid); ok "PR уже смержен: ${ref:0:7} — шаги 1–3 пройдены, дальше cd-staging (шаг 4)" ;;
  OPEN)   ref="origin/$head"
          git rev-parse -q --verify "$ref" >/dev/null || git fetch -q origin "$head"
          if [ "$(f .isDraft)" = false ]; then ok "PR не draft"; else warn "PR в draft — перед merge: gh pr ready $pr"; fi
          case "$(f .mergeStateStatus)" in
            CLEAN)    ok "mergeState CLEAN" ;;
            BEHIND)   warn "ветка отстала от develop (защита strict) — gh pr update-branch $pr и снова ждать ci-gate" ;;
            DIRTY)    stop "конфликт с develop — разрешить в ветке главы" ;;
            BLOCKED)  warn "mergeState BLOCKED — обычно ci-gate ещё не зелёный" ;;
            *)        warn "mergeState $(f .mergeStateStatus) — перепроверить позже" ;;
          esac ;;
  *)      stop "PR в состоянии $state — закрывать нечего"; ref=origin/develop ;;
esac

# ci-gate — единственная обязательная проверка (ADR 0008).
gate=$(gh pr checks "$pr" --required --json name,bucket --jq '.[] | select(.name=="ci-gate") | .bucket' 2>/dev/null || true)
case "$gate" in
  pass)    ok "ci-gate зелёный" ;;
  pending) warn "ci-gate ещё идёт — gh pr checks $pr --watch --required" ;;
  fail|cancel) stop "ci-gate $gate — разобрать упавший job: gh pr checks $pr" ;;
  *)       warn "ci-gate не найден среди обязательных проверок (${gate:-нет данных})" ;;
esac

files=$(f '.files[].path')
show() { git show "$ref:$1" 2>/dev/null || true; }

where=${ref#origin/}; [ "$state" = MERGED ] && where=${ref:0:7}
echo "== DoD главы $nn (docs/MASTER_CHECKLIST.md @ $where)"
block=$(show docs/MASTER_CHECKLIST.md | awk -v n="$((10#$nn))" '
  $0 ~ "^\\*\\*Глава " n "\\." {on=1; print; next}
  on && /^\*\*Глава [0-9]+\./ {exit}
  on && /^\*\*Проверка и тестирование/ {show=1}
  on && show && NF')
if [ -n "$block" ]; then
  printf '%s\n' "$block" | sed 's/^/      /'
  if grep -q '^> Отклонени' <<<"$block"; then ok "отклонения от чек-листа записаны (сверить с ADR главы)"
  else info "записанных отклонений нет — каждый пункт DoD должен иметь доказательство"; fi
else
  warn "глава $nn не найдена в MASTER_CHECKLIST.md"
fi

echo "== Артефакты главы в PR"
grep -E '^docs/adr/0[0-9]{3}-' <<<"$files" | sed 's/^/OK    ADR: /' || warn "в PR нет ADR главы"
report=$(git ls-tree -r --name-only "$ref" docs/reviews | grep -E "_${nn}\.md$" || true)
if [ -n "$report" ]; then
  ok "отчёт: $report"
  # Незакрытые пункты в отчёте — повод сверить DoD до merge (глава 20: «NOT RUN» до прогонов на iPhone).
  open_items=$(show "$report" | grep -nE '\b(NOT RUN|BLOCKED)\b' | head -5 || true)
  [ -z "$open_items" ] || { warn "в отчёте есть NOT RUN/BLOCKED — сверить с DoD:"; printf '%s\n' "$open_items" | cut -c1-160 | sed 's/^/      /'; }
else
  warn "нет docs/reviews/*_$nn.md (в главах 17–25 отчёт был всегда)"
fi
grep -qE '[Нн]е выполнено по DoD' <<<"$(f .body)" \
  && stop "в теле PR «Не выполнено по DoD» — DONE невозможен: ждать, PARTIAL или отклонение (решает владелец)"
grep -qx docs/openapi.yaml <<<"$files" && info "контракт изменён — CI проверяет Spectral, gen:api, oasdiff (ADR 0007)" || true

echo "== Глоссарий и тег"
gl=$(show docs/requirements/GLOSSARY.md | grep -oE "Дополнения v1\.[0-9]+ — [0-9-]+ \(Глава $((10#$nn))," | tail -1 || true)
last=$(git tag -l 'requirements-baseline-v1.*' --sort=-v:refname | head -1)
info "последний baseline-тег: ${last:-нет}"
if [ -n "$gl" ]; then
  ver=$(sed -E 's/Дополнения (v1\.[0-9]+).*/\1/' <<<"$gl")
  tag="requirements-baseline-$ver"
  if git rev-parse -q --verify "refs/tags/$tag" >/dev/null; then
    ok "тег $tag уже есть → $(git rev-list -n1 "$tag" | cut -c1-7)"
  else
    ok "глоссарий $ver дополнен в главе $nn — после cd-staging нужен тег $tag (шаг 5)"
  fi
else
  info "глоссарий в главе $nn не дополнялся — baseline-тег не нужен, если ADR главы не требует иного"
fi

echo "== Issue"
issues=$(f '[.closingIssuesReferences[].number] | map("#" + tostring) | join(", ")')
if [ -n "$issues" ]; then ok "merge закроет: $issues"
else warn "PR не закрывает Issue (Refs/нет Closes) — закрыть status-PR'ом (Closes #N), если DoD выполнен"; fi
if grep -qi 'thermo-nuclear' <<<"$(f .body)"; then info "в PR упомянуто ревью thermo-nuclear"
else info "ревью thermo-nuclear в PR не упомянуто — предложить владельцу /thermo-nuclear-code-quality-review"; fi

echo "== PROJECT_STATUS.md (origin/develop)"
row=$(git show origin/develop:docs/PROJECT_STATUS.md | grep -E "^\| ($nn|$nn–[0-9]+|[0-9]+–[0-9]+) \|" | awk -F'|' -v n="$((10#$nn))" '
  { split($2, r, "–"); lo = r[1] + 0; hi = (r[2] == "" ? lo : r[2] + 0); if (n >= lo && n <= hi) print }' | head -1)
info "$(cut -c1-160 <<<"${row:-строки нет}")"
date_line=$(git show origin/develop:docs/PROJECT_STATUS.md | grep -m1 '^Обновлено:' || true)
info "${date_line:-строки «Обновлено:» нет}"

echo
if [ "$stops" -gt 0 ]; then
  echo "ИТОГ: $stops STOP — merge не выполнять; доработать или спросить владельца (шаг 1)."
else
  echo "ИТОГ: стоп-пунктов нет. WARN — проверить; пункты DoD сверить по доказательствам вручную."
fi
