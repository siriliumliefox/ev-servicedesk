# Сводка OWASP ZAP — прогон 3, итоговый (после ревью), 2026-10-18, образ из 079577e

| Проход | High | Medium | Low | Info |
|---|---|---|---|---|
| api-admin | 0 | 0 | 0 | 2 |
| api-anonymous | 0 | 0 | 0 | 2 |
| api-client | 0 | 0 | 0 | 2 |
| api-engineer | 0 | 0 | 0 | 2 |
| web-web-admin | 0 | 0 | 1 | 2 |
| web-web-engineer | 0 | 0 | 1 | 2 |

## Находки

| Проход | Уровень | Правило | Находка | Число | Пример |
|---|---|---|---|---|---|
| api-admin | Informational | 100000 | A Client Error response code was returned by the server | 152 | `DELETE /v1/decision-tree-nodes/10` |
| api-admin | Informational | 10049 | Non-Storable Content | 5 | `GET /v1/knowledge-articles` |
| api-anonymous | Informational | 100000 | A Client Error response code was returned by the server | 210 | `DELETE /v1/auth/pd-consent` |
| api-anonymous | Informational | 10049 | Non-Storable Content | 5 | `GET /v1/aggregate-status-thresholds` |
| api-client | Informational | 100000 | A Client Error response code was returned by the server | 92 | `DELETE /v1/push-tokens/token` |
| api-client | Informational | 10049 | Non-Storable Content | 5 | `DELETE /v1/push-tokens/token` |
| api-engineer | Informational | 100000 | A Client Error response code was returned by the server | 87 | `GET` |
| api-engineer | Informational | 10049 | Non-Storable Content | 5 | `GET /v1/knowledge-articles/10/decision-tree` |
| web-web-admin | Low | 90004 | Cross-Origin-Embedder-Policy Header Missing or Invalid | 3 | `GET /` |
| web-web-admin | Informational | 10049 | Storable but Non-Cacheable Content | 5 | `GET /` |
| web-web-admin | Informational | 10109 | Modern Web Application | 2 | `GET /` |
| web-web-engineer | Low | 90004 | Cross-Origin-Embedder-Policy Header Missing or Invalid | 3 | `GET /` |
| web-web-engineer | Informational | 10049 | Storable but Non-Cacheable Content | 5 | `GET /` |
| web-web-engineer | Informational | 10109 | Modern Web Application | 3 | `GET /` |
