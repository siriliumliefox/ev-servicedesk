# Веб-кабинет инженера

React + TypeScript + Vite + Tailwind (npm workspace). Канбан-доска тикетов, карточка тикета с контекстом
авто и чатом, быстрые ответы из базы знаний, тёмная тема. Решения — ADR 0012 (прототип, глава 8) и
ADR 0025 (реальный API, глава 21).

## Режимы

| Запуск | Данные |
|---|---|
| `npm run dev -w web-engineer` | прототип на фикстурах (`PrototypeRepository`, панель «Демо») |
| `VITE_API_BASE_URL=/v1 EV_API_PROXY=http://127.0.0.1:8000 npm run dev -w web-engineer` | реальный API: вход инженера, Vite проксирует `/v1` (REST и WebSocket) на backend |
| сборка staging/production | `VITE_API_BASE_URL=/v1` (тот же origin, прокси nginx — глава 26), `VITE_MEDIA_ORIGIN` — origin S3 для фото и видео вложений; CSP — `<meta>` в `index.html` |

## Проверки

```bash
npm test -w web-engineer                 # Vitest: доска, карточка, перенос с клавиатуры, вход, живые события
web-engineer/scripts/e2e.sh              # Playwright на стеке из образа-кандидата: Chromium, Firefox, WebKit
web-engineer/scripts/engineer_run.sh     # ручная проверка: стек, 2 инженера, кабинет на :5175 (MOBILE=1 — и iOS Simulator)
```

Входы инженеров для ручной проверки — в `~/.config/ev-servicedesk/engineers.local` (0600), в репозиторий
не попадают. Отчёт и чек-лист — `docs/reviews/ENGINEER_WEB_21.md`.
