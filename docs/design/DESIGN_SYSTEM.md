# Дизайн-система EV-ServiceDesk

Глава 6, Issue #34, ADR 0010. Источник истины — [`design/tokens.json`](../../design/tokens.json).

| Что | Где |
|---|---|
| Токены (DTCG) | `design/tokens.json` |
| Генератор / тесты | `scripts/design_tokens.mts` (`npm run tokens`), `scripts/design_tokens.test.mts` (`npm run test:tokens`, CI `web-ci`) |
| Веб | `web-shared/src/theme/` (`tokens.css` — генерируется, `theme.css`, `useTheme`), компоненты `StatusBadge`, `Button`, `TextField`, `Card` |
| Flutter | `mobile/lib/theme/` (`tokens.g.dart` — генерируется, `app_theme.dart`), `mobile/lib/ui/` (`StatusBadge`, `EvBottomNav`, состояния `states.dart`), тесты `mobile/test/design_system_test.dart`; экраны — `docs/design/MOBILE_PROTOTYPE.md` |
| Figma | [EV-ServiceDesk Design System](https://www.figma.com/design/mgvOfQ9AizhhPMpBhxA3b5) — файл команды, тариф Starter, не опубликован (см. ниже) |

## Бренд
ETS AUTO (головной филиал, https://ets-auto.by): жёлтый `#f9ce12` на тёмном `#171717`, шрифт Inter.
Жёлтый — **только заливка** с тёмным текстом: на белом он даёт 1.5:1. Ссылки и акцентный текст на светлом
фоне — `primary-text` `#7a5c00`.

## Цвета (семантические токены)
Интерфейс использует только семантические токены; примитивы (`color.*`) — для их определения.

| Токен | Светлая | Тёмная | Назначение |
|---|---|---|---|
| `canvas` / `surface` / `surface-subtle` | `#fafafa` / `#ffffff` / `#f4f4f5` | `#0f0f10` / `#18181b` / `#27272a` | фон страницы / карточки, поля / вторичные блоки |
| `fg` / `fg-muted` / `fg-disabled` | `#171717` / `#52525b` / `#a1a1aa` | `#f4f4f5` / `#a1a1aa` / `#52525b` | текст |
| `border` / `border-strong` | `#e4e4e7` / `#71717a` | `#3f3f46` / `#71717a` | разделители / границы полей |
| `primary` / `primary-hover` / `on-primary` | `#f9ce12` / `#e6bc00` / `#171717` | `#f9ce12` / `#ffd83d` / `#171717` | основная кнопка, индикатор навигации |
| `primary-text` | `#7a5c00` | `#f9ce12` | ссылки, акцент |
| `focus-ring` | `#171717` | `#f9ce12` | фокус клавиатуры |
| `danger` / `on-danger` / `danger-text` | `#b91c1c` / `#ffffff` / `#b91c1c` | `#f87171` / `#171717` / `#f87171` | опасные действия, ошибки |
| `info-text` | `#004f91` | `#60a5fa` | информационный текст |

### Светофор
Статус передаётся **цветом, формой иконки и подписью** (ТЗ раздел 6). Подписи — из глоссария.

| Статус | Подпись | Иконка | bg / fg / solid (светлая) | bg / fg / solid (тёмная) |
|---|---|---|---|---|
| `green` | Заменено | круг с галочкой | `#dcfce7` / `#166534` / `#15803d` | `#052e16` / `#86efac` / `#22c55e` |
| `yellow` | Скоро менять | треугольник | `#fef3c7` / `#92400e` / `#b86e00` | `#451a03` / `#fcd34d` / `#f59e0b` |
| `red` | Требуется замена | восьмиугольник с крестом | `#fee2e2` / `#991b1b` / `#dc2626` | `#450a0a` / `#fca5a5` / `#ef4444` |
| `unknown` | Нет данных | круг с вопросом | `#f4f4f5` / `#3f3f46` / `#71717a` | `#27272a` / `#d4d4d8` / `#a1a1aa` |

`bg`/`fg` — бейдж, `solid` — заливка агрегата на интерактивной схеме и точка-индикатор.
«Скоро менять» — янтарный, а не брендовый жёлтый: оттенок `solid` отличается от `primary` ≥ 10° (тест).

## Контраст (WCAG 2.1 AA)
Проверяется автоматически: `npm run test:tokens`, 100 проверок (обе темы). Текст ≥ 4.5:1; иконки, границы
полей, фокус и заливки статусов ≥ 3:1 — на `canvas`, `surface` и `surface-subtle`. Минимумы по группам:

| Пара | Мин. | Светлая | Тёмная |
|---|---|---|---|
| `fg` на `surface` | 4.5 | 17.93 | 16.12 |
| `fg-muted` на `surface` / `canvas` | 4.5 | 7.73 / 7.41 | 6.91 / 7.48 |
| `primary-text` на `surface` | 4.5 | 6.25 | 11.70 |
| `on-primary` на `primary` | 4.5 | 11.84 | 11.84 |
| `on-danger` на `danger` | 4.5 | 6.47 | 6.48 |
| `status-*-fg` на `status-*-bg` | 4.5 | 6.37 … 9.50 | 8.51 … 10.62 |
| `border-strong` на `surface` | 3 | 4.83 | 3.67 |
| `focus-ring` на `surface` | 3 | 17.93 | 11.70 |
| `status-*-solid` на `surface-subtle` | 3 | 3.63 … 4.56 | 3.96 … 6.94 |

Ручная проверка в Figma плагином Stark / Contrast Checker — владелец (см. «Статус»).

## Типографика — Inter
Sora с сайта ETS AUTO не используется: в нём нет кириллицы. Веб — `@fontsource-variable/inter`
(локально, без Google Fonts). Flutter — системный шрифт до ассета Inter (глава 18).

| Стиль | Mobile (Flutter) | Web (`text-*`) |
|---|---|---|
| display | 28/34 Bold | 32/40 Bold |
| h1 | 24/30 Bold | 26/34 Bold |
| h2 | 20/28 Semi Bold | 20/28 Semi Bold |
| h3 | 17/24 Semi Bold | 16/24 Semi Bold |
| body | 16/24 Regular | 15/22 Regular |
| body-sm | 14/20 Regular | 13/18 Regular |
| label | 16/20 Semi Bold | 14/20 Semi Bold |
| caption | 12/16 Medium | 12/16 Medium |

## Отступы, радиусы, размеры
- Отступы — сетка 4: `0 4 8 12 16 20 24 32 40 48 64` (`space.N` = N × 4; Tailwind `p-N`, Flutter `EvSpace.sN`).
- Радиусы: `none 0`, `sm 4`, `md 8`, `lg 12`, `xl 20`, `full`.
- Тап-зона ≥ **44×44** (`size.tap-target-min`); мобильные контролы 48, нижняя навигация 64;
  веб-контролы 40 / 32 (мышь; WCAG 2.5.8 ≥ 24).

## Компоненты
| Компонент | Варианты (Figma) | Веб | Flutter |
|---|---|---|---|
| Button | Style: Primary/Secondary/Ghost/Danger × Size: Mobile/Web/Web SM × State: Default/Disabled | `Button` | `FilledButton` / `OutlinedButton` / `TextButton` (`evTheme`) |
| TextField | State: Default/Focus/Error/Disabled × Platform: Web/Mobile | `TextField` | `TextField` + `InputDecorationTheme` |
| Card | слот для бейджа | `Card` | `Card` (`CardThemeData`) |
| StatusBadge | Status: Green/Yellow/Red/Unknown | `StatusBadge`, `StatusIcon` | `StatusBadge` |
| NavItem / BottomNav | State: Default/Selected; иконка — свойство Icon | — | `EvBottomNav` (`NavigationBar`) |
| Tabs | — (глава 7) | — | `TabBar` (`TabBarThemeData`): текст `fg`/`fg-muted`, подчёркивание `primary-text` |
| Chip (выбор/фильтр) | — (глава 7) | — | `ChoiceChip` (`ChipThemeData`): выбранный — заливка `primary`, текст `on-primary` |

## Чек-лист консистентности
- [x] Все цвета — семантические токены; палитра Tailwind по умолчанию отключена (`--color-*: initial`).
- [x] Отступы и gap — шкала `space` (кратны 4, тест); радиусы — только `radius.*` (тест).
- [x] Кнопки и поля — `radius.md`; карточки — `radius.lg`; боттом-шит — `radius.xl`; бейджи — `radius.full`.
- [x] Мобильные контролы ≥ 44 (48), нижняя навигация 64 (тесты `flutter test`); веб 40 / 32.
- [x] Статус = цвет + форма иконки + подпись; подписи одинаковы в вебе, Flutter и глоссарии (тест).
- [x] Текст — только стили `typography.*` (`text-*` в вебе, `EvTypeMobile` во Flutter).
- [x] Межстрочный ≥ кегля, кратен 2; кегль ≥ 12; мобильный body ≥ 16 (тест).

## Figma и тариф Starter
Ограничения Starter и обходы (ADR 0010, п. 6):
- 1 режим на коллекцию → тёмная тема — отдельная коллекция `Color Dark` (те же имена, что `Color Light`);
- 3 страницы → `Cover & Foundations`, `Components`, `Engineer · Dark`;
- публикация командной библиотеки недоступна → файл доступен по ссылке, **не опубликован**;
- лимит вызовов MCP → страница `Engineer · Dark` собирается скриптом `design/figma/engineer-dark.js` после сброса лимита.

После перехода на Education: объединить `Color Light`/`Color Dark` в `Color` (режимы Light/Dark),
разнести Cover и Foundations, **Publish** библиотеки.

## Решено в главе 7
- Нижняя навигация — 4 пункта по ТЗ (раздел 9): «Авто» / «Обучение» / «Поддержка» / «Новости»;
  уведомления — лента «Новости» со счётчиком непрочитанных на пункте (ADR 0011). Подпись «Уведомления»
  в навигации больше не нужна. В Figma `NavItem`/`BottomNav` — обновить подписи при переходе на Education.
- Вкладки и чипы: брендовый жёлтый на белом даёт 1.5:1, поэтому текст активной вкладки — `fg`, а жёлтый —
  только заливка выбранного чипа с `on-primary` (тест `mobile/test/design_system_test.dart`).
