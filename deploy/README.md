# deploy/ — production-инфраструктура

Глава 26, [ADR 0030](../docs/adr/0030-production-infrastructure.md). Две ВМ (staging, production) на Docker
Compose: приложение (`compose.yml`) и мониторинг (`compose.monitoring.yml`) — одинаковые, окружение —
метка и `env/<окружение>.env`.

| Путь | Что |
|---|---|
| `compose.yml` | PostgreSQL 16 + pgBackRest, Redis (AOF), миграции, API, 3 worker'а, nginx, certbot |
| `compose.monitoring.yml` | Prometheus, Alertmanager, Grafana, Loki, Alloy, экспортёры, blackbox |
| `compose.local.yml` | локальный стенд: сети «провайдера» и «интернета», УЦ стенда |
| `env/` | переменные окружений (не секреты) |
| `nginx/` | TLS, HSTS, CSP, `/v1` и WebSocket, журнал без строки запроса |
| `postgres/` | образ, `postgresql.conf` (ADR 0028), `pgbackrest.conf` |
| `prometheus/` | шаблон конфигурации, правила алертов и их тесты |
| `alertmanager/`, `loki/`, `alloy/`, `grafana/`, `blackbox/` | маршруты алертов, журналы, дашборды |
| `load/nightly.js` | ночной облегчённый прогон k6 на staging |
| `stand/` | провайдер локального стенда (MinIO, реестр, приёмник алертов) |
| `scripts/` | `bootstrap.sh` (ВМ), `deploy.sh` (выкладка, откат), `backup.sh`, `restore.sh`, `certs.sh`, `ev-ssh` (forced command), `make-bundle.sh`, `render-secrets.sh`, `render.py`, `check-configs.sh`, `nightly-load.sh` |

Проверка без серверов: `deploy/scripts/check-configs.sh` (job `infra` в `ci-gate`). Стенд и учения:
`scripts/infra_stack.sh up|drill-rollback|drill-dr|drill-alerts|down` (workflow `infra-drill.yml`).
Runbook'и — `docs/runbooks/`: выкладка и откат, восстановление, алерты, инцидент ПД, действия владельца.
