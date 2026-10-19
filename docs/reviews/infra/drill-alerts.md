# Тест алертов (стенд) — 2026-10-18T23:15:43Z
- канал: приёмник стенда; цель critical — ≤ 300 с от сбоя до уведомления

| Сбой | Алерт | Секунд до уведомления | Итог |
|---|---|---|---|
| остановлен backend | ServiceDown | 160 | PASS |
| остановлен PostgreSQL под нагрузкой 2 rps | HighErrorRate | 178 | PASS |
| (тот же сбой) | PostgresDown | 101 | PASS |
| остановлен notifications-worker | WorkerDown | 180 | PASS |
| недоступен production (nginx) — видно с staging | PeerDown | 170 | PASS |
| (постоянно) | Watchdog → dead-man | сигналов от staging: 21 | PASS |
