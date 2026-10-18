# Шаблоны закрытия главы

Подставить факты; пустые поля не оставлять — нет факта, значит нет и пункта.

## Строка главы в docs/PROJECT_STATUS.md

Одна строка таблицы, без переносов:

```
| NN | <Название из MASTER_CHECKLIST> | DONE | Issue #I (закрыт), PR #P (`sha7` в `develop`), ADR NNNN (<grill-with-docs/grilling Q1–Qn>; <решения владельца>), глоссарий v1.N («Термин», «Термин»), <RBAC-NN>, <контракт X.Y.Z (аддитивно: …)>, тег `requirements-baseline-v1.N`. Сделано: <главное, 3–6 пунктов через «;»>. Отчёт — `docs/reviews/<ТЕМА>_NN.md`. <Отклонения: … (ADR NNNN п. …)>. cd-staging `<run>` |
```

`PARTIAL`: то же, плюс «Не выполнено по DoD: …», и Issue «(открыт)».

Если глава была в диапазоне `| NN–28 | см. \`MASTER_CHECKLIST.md\` | NOT_STARTED | — |`, после строки
главы оставить `| NN+1–28 | см. \`MASTER_CHECKLIST.md\` | NOT_STARTED | — |`.

В строке `01` дописать в список тегов: `` `requirements-baseline-v1.N` (глоссарий, PR #P)``.

## Тег

```
git tag -a requirements-baseline-v1.N <sha> -m "Глоссарий v1.N (глава NN, ADR NNNN): «Термин», «Термин»"
```

Релизный тег (только по решению владельца):

```
git tag -a vX.Y.Z[-rc.K] <sha> -m "EV-ServiceDesk vX.Y.Z — <что это> (глава NN, #I): <доказательства — прогоны, принято владельцем ДАТА>"
```

## Коммит status-PR

```
docs(status): глава NN → DONE (#I)

Co-Authored-By: <трейлер агента>
```

## Тело status-PR

```
Глава NN «<Название>» → **DONE**.

- PR #P смержен (`sha7`), CI зелёный<, ревью thermo-nuclear — N находок исправлено>.
- DoD: <пункт — как выполнен, кто проверял>; <отклонения — ADR NNNN п. …>.
- cd-staging `<run>` — success (smoke X/X, интеграционный стек PASS, regression success).
- Тег `requirements-baseline-v1.N` (глоссарий «…»).

Closes #I

🤖 Generated with [Claude Code](https://claude.com/claude-code)
```

`PARTIAL`: заголовок `docs(status): глава NN → PARTIAL (#I)`, в теле — «Не выполнено по DoD: …»,
`Refs #I` вместо `Closes`.
