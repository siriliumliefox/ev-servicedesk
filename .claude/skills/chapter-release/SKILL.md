---
name: chapter-release
description: >-
  Закрытие главы EV-ServiceDesk, когда реализация готова: сверка DoD с MASTER_CHECKLIST и ADR →
  зелёный ci-gate → squash-merge PR главы в develop → cd-staging (smoke образа, интеграционный стек,
  regression) → тег (requirements-baseline-v1.N, при решении — релизный) → status-PR с
  PROJECT_STATUS.md → merge status-PR и закрытое Issue. Использовать всегда, когда в EV-ServiceDesk
  просят «закрой главу», «доведи главу NN до DONE», «мержим главу», «глава → DONE/PARTIAL», «что
  осталось до DONE», «поставь тег baseline», «сделай status-PR», «после merge — тег и статус», или
  когда PR ветки feature/… главы готов и CI зелёный, или cd-staging упал после merge главы, даже
  если скилл не назван. Также для сухого прогона закрытия без реальных действий. Только главы
  проекта EV-ServiceDesk (MASTER_CHECKLIST, 28 глав), не курсовой и не диплома. Не для начала главы
  (grilling, ADR, реализация), не для dependabot/hotfix-PR вне главы и не для релиза в main.
---

# Закрытие главы EV-ServiceDesk

Одна глава = одна ветка = один PR в `develop`, затем cd-staging, тег и отдельный status-PR. Эта
рутина повторялась в главах 10–25; фактический порядок восстановлен по git и PR — см.
`references/history.md`. Скилл нужен, чтобы ни один шаг не потерялся и глава не стала `DONE` без
доказательств: по AGENTS.md `DONE` — только при выполненном оригинальном DoD, зелёном CI и
смерженном PR, иначе `PARTIAL`/`BLOCKED`.

Приоритет: AGENTS.md, ADR 0008 (защита веток), ADR 0002 (baseline утверждает владелец) и ADR главы
важнее этого скилла. Если они расходятся со скиллом — следовать им и сказать владельцу о расхождении.

Общение — по-русски. Статусы проверок: `PASS`, `FAIL`, `NOT RUN`, `BLOCKED`.

## Входные данные

Номер главы `NN`, Issue главы и PR главы. Если не названы — найти:

```bash
# заголовки PR глав: «Глава NN: …» или «feat(NN): …»; ветка feature/<issue>-<slug>
gh pr list --state all --limit 40 --json number,title,state,headRefName \
  --jq '.[] | select(.title | test("^(Глава NN[:.]|[a-z]+\\(NN\\))")) | "#\(.number) \(.state) \(.headRefName) \(.title)"'
```

Скрипты скилла лежат рядом с этим файлом (в репозитории — `.claude/skills/chapter-release/scripts/`),
запускаются из корня клона, только читают и годятся для сухого прогона:

- `scripts/preflight.sh <PR> [NN]` — шаги 1–2: состояние PR, ci-gate, DoD главы из чек-листа,
  отклонения, ADR, отчёт, глоссарий и нужный тег, Issue, строка PROJECT_STATUS.
- `scripts/staging_evidence.sh <sha>` — шаг 4: прогон cd-staging по коммиту, jobs, итог smoke и
  интеграционного стека, digest образа и готовая строка для status-PR.

## Сухой прогон

Если просят «проверь», «сухой прогон», «dry run», «что осталось», «как бы ты закрыл» — выполнять
только чтение (`git fetch/log/show`, `gh pr view/checks`, `gh run list/view`, оба скрипта). Каждое
изменяющее действие (merge, `update-branch`, `ready`, тег, push, создание PR, правка файлов) не
выполнять, а печатать готовой командой с пометкой `[DRY-RUN]`. В конце — тот же итоговый отчёт с
пометкой «сухой прогон». Ничего не мержить, не тегировать и не пушить.

## Шаги

### 0. Контекст

`git fetch origin --tags --prune`; работать в своём worktree или проверять `git branch --show-current`:
параллельные сессии в общем checkout переключают ветки. Прочитать главу NN в `docs/MASTER_CHECKLIST.md`
(разделы «Проверка и тестирование» и «Критерий готовности (Definition of Done)»), ADR главы, строку
главы в `docs/PROJECT_STATUS.md`, тело PR главы.

### 1. Сверка DoD — первая точка остановки

Запустить `scripts/preflight.sh <PR>`, затем по каждому пункту «Проверки» и DoD из чек-листа найти
доказательство: тест, прогон CI с id, отчёт `docs/reviews/<ТЕМА>_NN.md`, запись в ADR. Составить
таблицу «пункт — PASS/FAIL/NOT RUN/BLOCKED — доказательство». Скрипт сам DoD не проверяет: он только
показывает пункты и наличие артефактов, решение по пункту — за тобой, по фактам.

Что должно быть в PR главы, а не в status-PR (так было в главах 17–25): ADR главы, отчёт
`docs/reviews/*_NN.md`, отклонения от чек-листа строкой `> Отклонения (решения ДАТА, ADR NNNN): …`
под главой в MASTER_CHECKLIST, дополнение глоссария `Дополнения v1.N — дата (Глава NN, ADR NNNN)`.
Галочки `☐` в чек-листе в этом проекте не ставятся — доказательства живут в PROJECT_STATUS и отчёте.

**Стоп, решает владелец** (спросить вопросом с готовыми вариантами, рекомендуемый первым):

- пункт DoD не выполнен и отклонение не записано. Варианты: доделать до merge (рекомендуется);
  смержить и закрыть главу как `PARTIAL`, Issue остаётся открытым (глава 20: PR #85 → status-PR #86,
  потом #99); принять отклонение — записать в ADR и MASTER_CHECKLIST (глава 22, Q20);
- пункт требует действия владельца: прогон на реальном устройстве, подпись приёмки RC, ввод ключей,
  проверка сотрудником, запуск скилла «запускает владелец». Агент не выполняет его вместо владельца
  без прямого поручения; если поручение есть — отметить в отчёте «по поручению владельца».

Перед merge предложить владельцу `/thermo-nuclear-code-quality-review` (запускает владелец). Не
блокироваться, если он его пропускает: в главах 22 и 23 ревью прошло после merge отдельным PR
(#95, #110).

### 2. Зелёный ci-gate

`ci-gate` — единственная обязательная проверка; защита `develop` требует актуальную ветку (strict),
линейную историю и действует на админа (ADR 0008).

```bash
gh pr ready <PR>                                  # если draft
gh pr view <PR> --json mergeStateStatus,mergeable # BEHIND → обновить ветку:
gh pr update-branch <PR>
gh pr checks <PR> --watch --required              # ждать в фоне, не опрашивать вручную
```

Красный job — разобрать (`gh pr checks <PR>`, `gh run view <run> --log-failed`) и чинить в ветке
главы. Нельзя: `--admin`, `--no-verify`, менять защиту веток, пушить в `develop` напрямую. Аварийный
обход защиты — только сам владелец через `scripts/setup-branch-protection.sh` с записью в PR.

### 3. Squash-merge PR главы

Владелец разрешил агенту мержить самому после зелёного ci-gate (2026-10-11). Если ты работаешь без
такого разрешения (другой агент или новое указание владельца) — спросить перед merge.

```bash
head=$(gh pr view <PR> --json headRefOid --jq .headRefOid)   # голова, на которой зелёный ci-gate
gh pr merge <PR> --squash --match-head-commit "$head" --subject "Глава NN: <название> — <суть> (#<PR>)"
gh pr merge <PR> --squash --auto      # если CI ещё идёт: merge сам после зелёного ci-gate
gh pr view <PR> --json state,mergeCommit --jq '.state, .mergeCommit.oid'   # SHA для шагов 4–6
```

Ветка удаляется автоматически (`delete_branch_on_merge`). Несколько PR в очереди мержить по одному:
после каждого merge следующему нужен `update-branch` и новый ci-gate.

### 4. cd-staging, smoke и regression

Push в `develop` запускает `cd-staging.yml`, если затронуты его пути (backend, web, mobile,
system-e2e, compose, связанные workflow): сборка образа → `smoke_backend_image.sh` →
`integration_stack.sh` → публикация `backend:staging` и `backend:staging-<sha>` в ghcr.io →
сборка web → `deploy-staging` (до главы 26 заглушка, ADR 0008 п. 6) → `regression.yml` по
опубликованному digest.

```bash
gh run list --workflow cd-staging.yml --commit <sha> --json databaseId,status,conclusion
gh run watch <run> --exit-status                  # в фоне
scripts/staging_evidence.sh <sha>                 # jobs, smoke X/Y, стек, digest, строка для статуса
```

Digest брать из вывода скрипта (строка `pushing manifest … backend:staging-<sha>@sha256:…`), а не
из первого `Digest:` в логе: тот относится к сервису redis — так в строку главы 21 попал чужой digest.
`gh run watch` иногда выходит раньше времени — перед выводами убедиться, что
`gh run view <run> --json status` вернул `completed`. Если глава не тронула пути workflow, прогона не
будет — это не ошибка, в статус пишется «cd-staging не требуется». Красный прогон: один перезапуск
при известном флейке (`gh run rerun <run> --failed`, нестабилен `android-ui-e2e`), иначе — fix-PR
`fix(NN): …` (как #118 в главе 24); пока cd-staging не зелёный, глава не `DONE`.

Проверки «после merge», которых требует ADR главы, выполнить сейчас и сохранить id прогона для
status-PR (глава 24: контрольный `load.yml` на опубликованном образе по digest).

### 5. Тег — вторая точка остановки

| Тег | Когда | На какой коммит |
|---|---|---|
| `requirements-baseline-v1.N` | в главе дополнен глоссарий / RBAC / бэклог (ADR 0002: изменение baseline = PR + новый тег); N — из строки «Дополнения v1.N» глоссария | squash-коммит PR главы |
| релизный (`backend-v1.0-beta`, `v1.0.0-rc.1`, …) | только если его требует DoD/ADR главы и есть решение владельца (приёмка RC) | коммит, чей образ прошёл staging (записать run и digest) |

Тег ставить после зелёного cd-staging. Тег аннотированный, номер не переиспользуется:

```bash
git fetch origin --tags
git tag -l 'requirements-baseline-v1.*' --sort=-v:refname | head -3
git merge-base --is-ancestor <sha> origin/develop && ! git rev-parse -q --verify refs/tags/<tag>
git tag -a <tag> <sha> -m "Глоссарий v1.N (глава NN, ADR NNNN): «Термин», «Термин»"
git push origin <tag>
gh release create <релизный тег> --target <sha> --prerelease --title "…" --notes-file <файл>  # только RC/beta
```

**Стоп, решает владелец:** baseline утверждает владелец (ADR 0002). В главах 17–25 глоссарий
принимался в grill-with-docs/grilling главы — тогда решение уже есть в ADR, и тег ставит агент. Если
дополнение глоссария не прошло через владельца — спросить до тега. Релизный тег без записанного
решения владельца не ставить. Удалять или переносить опубликованный тег — только по решению владельца.

### 6. Status-PR

Отдельный PR от свежего `origin/develop`, ветка `chore/status-chapter-NN`. Обычно меняется только
`docs/PROJECT_STATUS.md`; отчёт и ADR — только если после merge что-то произошло (приёмка, контрольный
прогон, как в главе 23). Шаблоны строки, тела PR и коммита — `references/templates.md`.

```bash
git switch -c chore/status-chapter-NN origin/develop   # или отдельный worktree
```

В `docs/PROJECT_STATUS.md`:

1. Строка главы: статус `DONE` (или `PARTIAL` с перечнем невыполненного) и доказательства — Issue,
   PR и SHA в `develop`, ADR, глоссарий, тег, отчёт, отклонения, `cd-staging <run>`. Если глава
   внутри строки-диапазона «NN–28 | см. MASTER_CHECKLIST.md | NOT_STARTED» — вставить строку главы,
   диапазон сдвинуть на NN+1.
2. Строка `01`: дописать новый baseline-тег `requirements-baseline-v1.N` (глоссарий, PR #…).
3. `Обновлено: ГГГГ-ММ-ДД` — сегодняшняя дата.

```bash
python3 scripts/check_unicode_nfc.py
git add docs/PROJECT_STATUS.md && git diff --cached     # + поиск секретов; хук gitleaks — сам
git commit -m "docs(status): глава NN → DONE (#<issue>)"   # с трейлером Co-Authored-By
git push -u origin chore/status-chapter-NN
gh pr create --base develop --title "docs(status): глава NN → DONE (#<issue>)" --body-file <файл>
```

В теле — `Closes #<issue>`, если Issue не закрыл PR главы, и `Refs #<issue>` при `PARTIAL`.

### 7. Merge status-PR и проверка

```bash
gh pr merge <S> --squash --auto
gh pr checks <S> --watch --required
gh issue view <issue> --json state            # CLOSED при DONE
git fetch origin && git log --oneline -3 origin/develop
```

Status-PR меняет только docs, поэтому cd-staging по нему не запускается — это нормально.

Уборка: удалить свои worktree (`git worktree remove …`), обновить память главы, если она ведётся.
После крупного merge AGENTS.md велит переиндексировать MemPalace: `mempalace mine .` из корня клона.

## Итоговый отчёт

Писать владельцу кратко, по фактам, с id и SHA:

```
Глава NN «<название>» → DONE | PARTIAL | BLOCKED [сухой прогон]
| Шаг | Статус | Доказательство |
|---|---|---|
| DoD | PASS | пункты …, отчёт docs/reviews/…_NN.md, отклонения ADR NNNN п. … |
| ci-gate PR #P | PASS | run … |
| merge | PASS | `sha7` в develop |
| cd-staging | PASS | run …, smoke X/X, стек PASS, regression success, digest `sha256:…` |
| тег | PASS | requirements-baseline-v1.N → `sha7` |
| status-PR #S | PASS | `sha7`, Issue #I закрыт |
Не сделано / за владельцем: …
```

## Частые ситуации

- **Несколько PR в главе** (глава 23: #98, #101, #107; глава 24: #117 и fix #118) — в строку статуса
  все PR с SHA; тег — на коммит, который покрывает DoD.
- **PARTIAL → DONE позже** — второй status-PR `docs(status): глава NN → DONE — <что добавилось>` с
  доказательствами недостающих пунктов (главы 20, 23).
- **Шаг уже сделан** (тег стоит, status-PR открыт) — не повторять, проверить и перейти к следующему;
  `preflight.sh` показывает существующий тег.
- **Глава 26 и дальше**: `deploy-staging` становится реальным — смотреть, что ADR главы 26 требует
  проверять на сервере, и добавлять это к шагу 4.
