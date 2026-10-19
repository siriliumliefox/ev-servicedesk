# Нагрузочный прогон на сервере

ADR 0030 п. 20, ADR 0028. Два вида:

## Полный прогон ADR 0028 — на production-ВМ до запуска (один раз)
Пока на production нет данных клиентов: ВМ используется как стенд главы 24 в режиме staging с сидом,
затем тома удаляются и production инициализируется с нуля.
1. ВМ подготовлена (`bootstrap.sh production`), production ещё **не выкладывался**.
2. От администратора: `ssh -i ~/.ssh/ev_admin root@<IP production>`, затем
   `git clone https://github.com/siriliumliefox/ev-servicedesk && cd ev-servicedesk && npm ci` (Node 22).
3. Образ — опубликованный кандидат: `docker login ghcr.io` (временный токен с `read:packages` вводит
   владелец), `BACKEND_IMAGE=ghcr.io/siriliumliefox/ev-servicedesk/backend@sha256:…`.
4. Прогоны (ресурсы — как в `docker-compose.load.yml`, на ВМ без соседей):
   `scripts/load_stack.sh "$BACKEND_IMAGE" mixed peak` (дважды — финал ADR 0028 п. 13), затем
   `scripts/load_stack.sh "$BACKEND_IMAGE" soak`. Результаты — `load/results/<время>-<сценарий>/`
   (разбор `load/analyze.py`), нормативы — `docs/reviews/LOAD_TEST_24.md`; сравнение с прогоном на Mac —
   в отчёт главы 26.
5. `scripts/load_stack.sh` удаляет стенд сам; проверить `docker volume ls` — томов стенда нет; удалить
   клон репозитория и выйти из ghcr (`docker logout ghcr.io`). Затем — обычная выкладка production.
Если нормативы не достигнуты — фиксируется ёмкость, глава PARTIAL, решение владельца (ADR 0028 п. 17).

## Ночной облегчённый прогон — staging
`load-nightly.yml` в 02:30 по Минску: `ssh deploy@<staging> load staging` → `deploy/scripts/nightly-load.sh`
— k6 (20 VU, 5 мин, чтение главного экрана клиента и базы знаний) в сети staging напрямую в backend; вход
тестовым номером (`SMS_TEST_PHONES`); итоги — remote write в Prometheus staging, дашборд
«EV-ServiceDesk — нагрузка k6» (VU, RPS, p95/p99, доля ошибок). Нормативы — пороги сценария
(чтение p95 ≤ 300 мс, p99 ≤ 1 с, ошибки < 1 %): нарушение — красный прогон workflow.
