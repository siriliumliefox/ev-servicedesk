# Сводка OWASP ZAP — прогон 1 (до исправлений), 2026-10-18, образ из 7758f48

| Проход | High | Medium | Low | Info |
|---|---|---|---|---|
| api-admin | 0 | 0 | 1 | 2 |
| api-anonymous | 0 | 0 | 0 | 2 |
| api-client | 0 | 0 | 1 | 2 |
| api-engineer | 0 | 0 | 1 | 2 |
| web-web-admin | 0 | 2 | 5 | 2 |
| web-web-engineer | 0 | 2 | 5 | 2 |

## Находки

| Проход | Уровень | Правило | Находка | Число | Пример |
|---|---|---|---|---|---|
| api-admin | Low | 100000 | A Server Error response code was returned by the server | 2 | `GET /v1/users` |
| api-admin | Informational | 100000 | A Client Error response code was returned by the server | 152 | `DELETE /v1/decision-tree-nodes/10` |
| api-admin | Informational | 10049 | Non-Storable Content | 5 | `GET /v1/aggregate-status-thresholds` |
| api-anonymous | Informational | 100000 | A Client Error response code was returned by the server | 210 | `DELETE /v1/auth/pd-consent` |
| api-anonymous | Informational | 10049 | Non-Storable Content | 5 | `POST /v1/aggregate-types` |
| api-client | Low | 100000 | A Server Error response code was returned by the server | 1 | `GET /v1/vehicle-models` |
| api-client | Informational | 100000 | A Client Error response code was returned by the server | 92 | `DELETE /v1/push-tokens/token` |
| api-client | Informational | 10049 | Non-Storable Content | 5 | `GET /v1/tickets` |
| api-engineer | Low | 100000 | A Server Error response code was returned by the server | 1 | `GET /v1/vehicle-models` |
| api-engineer | Informational | 100000 | A Client Error response code was returned by the server | 87 | `GET` |
| api-engineer | Informational | 10049 | Non-Storable Content | 5 | `GET /v1/firmware-releases` |
| web-web-admin | Medium | 10020 | Missing Anti-clickjacking Header | 1 | `GET /` |
| web-web-admin | Medium | 10055 | CSP: Failure to Define Directive with No Fallback | 3 | `GET /` |
| web-web-admin | Low | 10021 | X-Content-Type-Options Header Missing | 5 | `GET /` |
| web-web-admin | Low | 10063 | Permissions Policy Header Not Set | 4 | `GET /` |
| web-web-admin | Low | 90004 | Cross-Origin-Embedder-Policy Header Missing or Invalid | 3 | `GET /` |
| web-web-admin | Low | 90004 | Cross-Origin-Opener-Policy Header Missing or Invalid | 3 | `GET /` |
| web-web-admin | Low | 90004 | Cross-Origin-Resource-Policy Header Missing or Invalid | 5 | `GET /` |
| web-web-admin | Informational | 10049 | Storable but Non-Cacheable Content | 5 | `GET /` |
| web-web-admin | Informational | 10109 | Modern Web Application | 3 | `GET /` |
| web-web-engineer | Medium | 10020 | Missing Anti-clickjacking Header | 2 | `GET /` |
| web-web-engineer | Medium | 10055 | CSP: Failure to Define Directive with No Fallback | 3 | `GET /` |
| web-web-engineer | Low | 10021 | X-Content-Type-Options Header Missing | 5 | `GET /` |
| web-web-engineer | Low | 10063 | Permissions Policy Header Not Set | 4 | `GET /` |
| web-web-engineer | Low | 90004 | Cross-Origin-Embedder-Policy Header Missing or Invalid | 3 | `GET /` |
| web-web-engineer | Low | 90004 | Cross-Origin-Opener-Policy Header Missing or Invalid | 3 | `GET /` |
| web-web-engineer | Low | 90004 | Cross-Origin-Resource-Policy Header Missing or Invalid | 5 | `GET /` |
| web-web-engineer | Informational | 10049 | Storable but Non-Cacheable Content | 5 | `GET /` |
| web-web-engineer | Informational | 10109 | Modern Web Application | 3 | `GET /` |
