# Как закрывались главы 17–25

Восстановлено 2026-10-19 по `git log origin/develop`, `git tag -n`, PR на GitHub и `gh run list`.
Это образцы, а не правило: при расхождении верны код, git, AGENTS.md и ADR.

| Глава | Issue | PR главы → squash в develop | cd-staging | Тег(и) | Status-PR |
|---|---|---|---|---|---|
| 17 Интеграция backend | #72 | #75 → `1aa55c9` | 38285162038 (smoke 44/44, стек PASS, digest `sha256:a08ebfaa…`) | `backend-v1.0-beta`, `requirements-baseline-v1.9` | #77 (`5c2fdb2`) |
| 18 Мобильный каркас | #76 | #78 → `991f09c` | 38300850900 | `requirements-baseline-v1.10` | #80 (`a2b9bf9`) |
| 19 Схема агрегатов | #79 | #81 → `8cfe0a9` | 38356643969 | `requirements-baseline-v1.11` | #84 (`1b0d603`); #82 закрыт как дубль |
| 20 Обучение, тикеты, уведомления | #83 | #85 → `e1c4cc2` | 38388796348 | `requirements-baseline-v1.12` | #86 PARTIAL (`f4fedfb`) → #99 DONE (`94d72f8`) |
| 21 Веб-кабинет инженера | #87 | #88 → `9553bfe` | 38409600901 | `requirements-baseline-v1.13` | #89 (`06191ad`) |
| 22 Админ-панель | #90 | #91 → `975363b` | 38457789443 | `requirements-baseline-v1.14` | #94 (`965ae8b`); ревью после merge — #95 |
| 23 Сквозное E2E | #96 | #98 `d3b33d1`, #101 `1021cb3`, #107 `7bd0579` | 38551939901 + regression 38553737009, 38555686379 (3/3) | `v1.0.0-rc.1` → `7bd0579` + pre-release | #108 PARTIAL (`907bbac`), #109 решения, #115 DONE (`99c014d`); ревью №2 — #110 |
| 24 Нагрузка | #116 | #117 → `d3257fb`, fix #118 → `eb2823b` | 38919526072 + regression; контроль `load.yml` 38932813807 | `requirements-baseline-v1.16` | #119 (`b96e0f4`) |
| 25 Безопасность | #120 | #121 → `42f302c` (закрыл #120, #102, #103) | 39141679712 (smoke 45/45, стек 21/21, regression success) | `requirements-baseline-v1.17` | #135 (`6e27aed`) |

## Закономерности

- **Merge** — всегда squash, заголовок `feat(NN): … (#issue) (#PR)` (главы 17–23) или
  `Глава NN: … (#PR)` (24–25). Часто через auto-merge, пока шёл CI.
- **Тег** — аннотированный, автор `siriliumliefox`, на squash-коммит PR главы; ставился в день merge.
  Сообщение: `Baseline требований v1.N: глоссарий — «…» (Глава NN, ADR NNNN, PR #P). Утверждено
  владельцем ДАТА.` (до v1.11), затем короче — `Глоссарий v1.N (глава NN, ADR NNNN): «…», «…»`
  (v1.16, v1.17; у v1.12–v1.14 варианты того же).
- **Status-PR** — ветка `chore/status-chapter-NN` (встречались `chore/status-NN`,
  `chore/<issue>-status-NN`, `docs/<issue>-status`), заголовок `docs(status): глава NN → DONE (#issue)`.
  Меняет только `docs/PROJECT_STATUS.md`; в главе 23 — ещё отчёт и ADR (итоги приёмки RC1).
- **Тело status-PR** — merge PR главы с SHA, id прогона cd-staging с итогом, тег, как выполнен DoD
  (кто проверял, отклонения), `Closes`/`Refs #issue`.
- **В PR главы, не в status-PR**: ADR, отчёт `docs/reviews/*_NN.md`, отклонения в MASTER_CHECKLIST,
  дополнение глоссария. Галочки `☐` в чек-листе не ставятся.
- **DoD с действием владельца** (прогон на iPhone, проверка в ролях, приёмка RC) — либо владелец,
  либо агент по прямому поручению с пометкой в ADR/отчёте (главы 20, 22, 23).

## Найденные расхождения (на 2026-10-19)

- Глоссарий v1.15 (глава 23, ADR 0027) есть, тега `requirements-baseline-v1.15` нет: глава 23
  закрыта тегом `v1.0.0-rc.1`. Ставить ли тег задним числом — решение владельца (ADR 0002).
- Строка `01` в PROJECT_STATUS перечисляет baseline-теги только до v1.12; v1.13, v1.14, v1.16,
  v1.17 не дописаны.
- `Обновлено:` в PROJECT_STATUS — 2026-10-14, хотя status-PR глав 24 и 25 смержены позже.
- В строке главы 21 записан «образ backend `sha256:858f009f…`», а это digest `redis:7-alpine` из шага
  `Initialize containers` прогона 38409600901; digest образа — в строке `pushing manifest … backend:staging-<sha>`.
