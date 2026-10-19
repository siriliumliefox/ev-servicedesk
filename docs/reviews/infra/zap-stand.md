# Сводка OWASP ZAP

| Проход | High | Medium | Low | Info |
|---|---|---|---|---|
| api-anonymous | 0 | 0 | 1 | 2 |
| api-client | 0 | 0 | 1 | 2 |
| web-admin | 0 | 0 | 1 | 4 |
| web-engineer | 0 | 0 | 1 | 4 |

## Находки

| Проход | Уровень | Правило | Находка | Число | Пример |
|---|---|---|---|---|---|
| api-anonymous | Low | 100001 | Unexpected Content-Type was returned | 11 | `GET` |
| api-anonymous | Informational | 100000 | A Client Error response code was returned by the server | 209 | `DELETE /v1/auth/pd-consent` |
| api-anonymous | Informational | 10049 | Non-Storable Content | 5 | `POST /v1/auth/phone/request-code` |
| api-client | Low | 100001 | Unexpected Content-Type was returned | 11 | `GET` |
| api-client | Informational | 100000 | A Client Error response code was returned by the server | 209 | `DELETE /v1/auth/pd-consent` |
| api-client | Informational | 10049 | Non-Storable Content | 5 | `DELETE /v1/auth/pd-consent` |
| web-admin | Low | 90004 | Cross-Origin-Embedder-Policy Header Missing or Invalid | 3 | `GET /` |
| web-admin | Informational | 10015 | Re-examine Cache-control Directives | 2 | `GET /` |
| web-admin | Informational | 10049 | Storable and Cacheable Content | 2 | `GET /assets/index-CfoX5LBU.js` |
| web-admin | Informational | 10049 | Storable but Non-Cacheable Content | 4 | `GET /` |
| web-admin | Informational | 10109 | Modern Web Application | 3 | `GET /` |
| web-engineer | Low | 90004 | Cross-Origin-Embedder-Policy Header Missing or Invalid | 3 | `GET /` |
| web-engineer | Informational | 10015 | Re-examine Cache-control Directives | 3 | `GET /` |
| web-engineer | Informational | 10049 | Storable and Cacheable Content | 2 | `GET /assets/index-C_7Bf78u.js` |
| web-engineer | Informational | 10049 | Storable but Non-Cacheable Content | 3 | `GET /` |
| web-engineer | Informational | 10109 | Modern Web Application | 3 | `GET /` |
