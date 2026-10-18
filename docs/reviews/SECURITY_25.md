# Глава 25 — Тестирование безопасности. Отчёт

Issue #120, ветка `feature/120-security-testing`, PR #121, ADR 0029 (grilling Q1–Q12), глоссарий v1.17
(«Анонимизация», «Срок хранения данных»), RBAC-06. Сжатые итоги сканирования — `docs/reviews/security/`,
сырые отчёты ZAP — вне git (`zap-results/`, в CI — артефакт workflow `security.yml`, ADR 0029 п. 7). Приложение к
пояснительной записке — `docs/Prilozhenie_Glava25_Security.docx` (ADR 0029 п. 20).

## Шаги чек-листа
| Шаг | Статус | Где |
|---|---|---|
| Чек-лист OWASP Top 10 по каждому сервису | PASS | таблица «OWASP Top 10:2025 × сервис» ниже; для API — сверка с API Security Top 10:2023, для мобильного приложения — сокращённый MASVS |
| Тест IDOR — чужой тикет/авто подменой ID | PASS | `test_idor_matrix.py` (9 операций `/vehicles/{id}/*` × 5 участников × активное/удалённое авто, 90 клеток, проверен мутацией), `test_ticket_security.py::test_object_level_matrix`; E2E-33 |
| Защита от SQL-инъекций и XSS в тикетах/чате | PASS | `test_injection.py` (12 нагрузок в описании, чате, статьях, поиске и фильтрах), Playwright — XSS в чате инженера не исполняется, Flutter — `MarkdownBody` без HTML и картинок; HTML в статьях — 422 |
| Автоматизированная проверка RBAC-матрицы по каждому эндпоинту | PASS | `test_rbac_matrix.py`: 63 защищённые операции контракта × 3 роли; роли — `x-required-roles`, их соответствие RBAC-матрице — `test_openapi_contract.py` |
| Пентест или сканирование (OWASP ZAP) | PASS | ZAP 2.17.0: API без токена и от client, engineer, admin + baseline двух кабинетов (`security.yml`, `scripts/zap_scan.sh`); пентест «чёрный ящик» не состоялся — раздел ниже |
| Все уязвимости классифицированы, критичные закрыты | PASS | таблица «Находки» ниже: CVSS v3.1 → S1–S4 (ADR 0029 п. 3) |
| Повторное сканирование — 0 критичных | PASS | «ZAP: до и после» ниже |

**DoD:** отчёт по безопасности оформлен и приложен к пояснительной записке: **PASS** — этот отчёт и `docs/Prilozhenie_Glava25_Security.docx`.

## Стенд
- Backend — образ из ветки (`backend/Dockerfile`, пользователь без root), режим `staging`, стек
  `scripts/integration_stack.sh`: одноразовые секреты, PostgreSQL 16, Redis 7, MinIO, worker'ы
  уведомлений, аналитики и ПД; логи стека проверяются на утечку секретов.
- Срок access-токена стенда — 2 ч (`INTEGRATION_ACCESS_TOKEN_TTL`): активный проход длиннее 15 мин.
- Участники — `backend/scripts/zap_prepare.py`: клиент с авто и тикетом, инженер с тикетом в работе,
  администратор (CLI образа). У каждой роли — свой контракт: только её операции, без завершающих
  сессию (выход, отзыв согласия, смена и сброс пароля, блокировка), — их проверяет проход без токена.
- Веб-кабинеты — production-сборка (CSP) в `vite preview` с прокси `/v1` на стенд.

## OWASP Top 10:2025 × сервис

Сервисы backend: **Auth** (вход, токены, согласие, Telegram), **Users**, **Veh** (Vehicle и Aggregates &
Maintenance), **Tick** (Tickets, Uploads, WebSocket), **KB** (Knowledge Base), **Notif** (Notifications,
push), **Anl** (Analytics); клиенты: **Web** (кабинет инженера и админ-панель), **Mob** (приложение
клиента). В клетке — PASS, N/A или номер находки; доказательства — [Д1]…[Д16] ниже.

| Пункт | Auth | Users | Veh | Tick | KB | Notif | Anl | Web | Mob |
|---|---|---|---|---|---|---|---|---|---|
| A01 Broken Access Control | PASS [Д1][Д4] | PASS [Д1] | PASS [Д1][Д2] | PASS [Д1][Д2] | PASS [Д1][Д2] | PASS [Д1][Д2] | PASS [Д1] | PASS [Д12] | PASS [Д12] |
| A02 Security Misconfiguration | PASS [Д8] | PASS [Д8] | PASS [Д8] | PASS [Д8] | PASS [Д8] | PASS [Д8] | PASS [Д8] | PASS [Д8] | PASS [Д13] |
| A03 Software Supply Chain Failures | PASS [Д9] | PASS [Д9] | PASS [Д9] | PASS [Д9] | PASS [Д9] | PASS [Д9] | PASS [Д9] | PASS [Д9] | PASS [Д9] |
| A04 Cryptographic Failures | PASS [Д10] | PASS [Д10] | PASS [Д10] | PASS [Д10] | N/A | PASS [Д10] | N/A | PASS [Д12] | PASS [Д13] |
| A05 Injection | PASS [Д6] | PASS [Д6] | PASS [Д6] | PASS [Д6][Д7] | PASS [Д6][Д7] | PASS [Д6] | PASS [Д6] | PASS [Д7] | PASS [Д7] |
| A06 Insecure Design | PASS [Д4][Д5] | PASS [Д4] | PASS [Д15] | PASS [Д15] | PASS [Д15] | PASS [Д15] | N/A | PASS [Д12] | PASS [Д13] |
| A07 Authentication Failures | PASS [Д3][Д4][Д5] | PASS [Д4] | PASS [Д3] | PASS [Д3] | PASS [Д3] | PASS [Д3] | PASS [Д3] | PASS [Д12] | PASS [Д13] |
| A08 Software or Data Integrity Failures | PASS [Д14] | PASS [Д14] | PASS [Д14] | PASS [Д14] | PASS [Д14] | PASS [Д14] | PASS [Д14] | PASS [Д9] | PASS [Д9] |
| A09 Security Logging & Alerting Failures | PASS [Д11] | PASS [Д11] | PASS [Д11] | PASS [Д11] | PASS [Д11] | PASS [Д11] | PASS [Д11] | N/A | PASS [Д13] |
| A10 Mishandling of Exceptional Conditions | PASS [Д16] | PASS [Д16] | PASS [Д16] | PASS [Д16] | PASS [Д16] | PASS [Д16] | PASS [Д16] | PASS [Д12] | PASS [Д13] |

API Security Top 10:2023 (сверка): API1 BOLA — [Д2]; API2 Broken Authentication — [Д3][Д4]; API3 Broken
Object Property Level Authorization — [Д1], ПД сотрудника скрыты от клиента (`test_ticket_privacy.py`),
лишние поля тел отклоняются схемами; API4 Unrestricted Resource Consumption — [Д5][Д15]; API5 Broken
Function Level Authorization — [Д1]; API6 Unrestricted Access to Sensitive Business Flows — [Д5][Д15];
API7 SSRF — N/A (сервер не загружает адреса пользователя; presigned URL подписываются для S3);
API8 Security Misconfiguration — [Д8]; API9 Improper Inventory Management — контракт — единственный
источник операций, deny by default (`test_rbac_contract.py`), Swagger скрыт в production; API10 Unsafe
Consumption of APIs — ответы A1 и FCM разбираются как данные, с тайм-аутами и повторами (ADR 0013, 0019).

## Доказательства
- **[Д1] RBAC.** `test_rbac_matrix.py` — 63 операции × 3 роли: чужая роль — 403 и для несуществующего id,
  своя — не отказ по роли; `test_rbac_contract.py` — у каждого маршрута проверка ролей (deny by default)
  и совпадение с контрактом; `test_openapi_contract.py` — роли контракта ⊆ RBAC-матрицы, матрица покрыта.
- **[Д2] Object-level.** `test_idor_matrix.py` (авто), `test_ticket_security.py::test_object_level_matrix`
  (тикеты, чат, WebSocket), `test_knowledge.py` (черновики — 404, RBAC-05), `test_notifications.py`
  (чужое уведомление и push-токен — 404), `test_ticket_attachments.py` (чужая загрузка). Невидимое — 404.
- **[Д3] Токены.** 11 видов отклонённых access-токенов (`alg=none`, чужая подпись, истёкший, refresh
  вместо access, подменённая роль — роль из БД), ротация refresh с обнаружением повтора.
- **[Д4] Сессии сотрудников (#102).** `test_session_security.py`: отзыв access при выходе, сбросе и смене
  пароля, повторе refresh; WebSocket закрывается 4401; Redis недоступен — 503; блокировка входа по паре
  «номер + IP» и потолок на номер; сброс пароля снимает блокировку; zxcvbn ≥ 3; смена пароля в лимите.
- **[Д5] SMS (#103).** Заблокированному клиенту и номеру сотрудника — тот же ответ без кода и SMS
  (`test_auth_flow.py::test_no_sms_for_blocked_client_or_staff`); лимиты SMS и ввода кода (ADR 0013 п. 6).
- **[Д6] Инъекции.** Только ORM и параметры, LIKE экранируется, `websearch_to_tsquery`; `test_injection.py` —
  нагрузки хранятся как есть, поиск не расширяет выборку, перечисления — 422; NUL и управляющие — 422.
- **[Д7] XSS.** Веб — текст React, `dangerouslySetInnerHTML` нет; Playwright — разметка в чате не
  исполняется; Flutter — `Text` и `MarkdownBody` без HTML и картинок; HTML в статье — 422; CSP сборки.
- **[Д8] Настройки.** `SecurityHeadersMiddleware` (nosniff, DENY, no-referrer, CORP, `no-store` на `/v1`),
  `test_security_headers.py`; Swagger скрыт в production; образ без root; fail closed: заглушки секретов,
  фейковые SMS и push запрещены вне local/test, бакет и настройки проверяются до старта (`app.preflight`).
- **[Д9] Цепочка поставок.** `dependency-audit` в `ci-gate`: pip-audit, `npm audit --omit=dev`, osv-scanner
  (`pubspec.lock`, `poetry.lock`); dependabot; gitleaks; образы стенда и сканеров — по digest.
- **[Д10] Криптография.** argon2id (пароли), HS256 с фиксированным алгоритмом и секретом ≥ 32 символов
  на окружение (`secrets-isolation.yml`), refresh — SHA-256, SMS-код — HMAC в Redis с TTL, вложения —
  presigned URL на 15 мин; TLS — nginx главы 26.
- **[Д11] Журналы.** Свой журнал доступа без строки запроса, `PiiFilter`, `test_log_privacy.py`; WARNING —
  подбор пароля с разных адресов; ERROR — клиент в очереди анонимизации дольше 14 дней. Сбор и оповещения —
  глава 26 (мониторинг).
- **[Д12] Веб-кабинеты.** Токен access — в памяти, refresh — в `sessionStorage` вкладки; только своя роль
  приложения; CSP `default-src 'self'`; API на том же origin (CORS нет); тексты ошибок по коду.
- **[Д13] Мобильное приложение (MASVS-lite).** Токены — Keychain/Keystore (`first_unlock_this_device`,
  без переноса), ATS без исключений, кроме локальной сети разработки, push без ПД, в логах — только тексты
  ошибок, ссылки статей — только http/https, картинки статей не загружаются.
- **[Д14] Целостность.** Только JSON по схемам Pydantic (нет десериализации объектов), схема БД — только
  Alembic, append-only журналы (`vehicle_mileage_correction`, версии статей, `pd_consent`), неизменяемость
  VIN/владельца триггером, образы по digest, подпись Telegram Login Widget.
- **[Д15] Бизнес-лимиты.** Тикеты 10/ч, сообщения 30/мин, presign 60/ч, добавление авто 10/ч, WebSocket —
  подключения с IP и на пользователя; граф статусов тикета и захват строк (главы 13, 24).
- **[Д16] Исключительные ситуации.** Единый формат ошибок без трассировки; id вне BIGINT — 404, а не 500;
  NUL — 422; Redis — 503 (fail closed); сбой S3 при анонимизации — откат и повтор; WebSocket — коды
  закрытия по виду отказа.

## ZAP: до и после

ZAP 2.17.0 (`ghcr.io/zaproxy/zaproxy` по digest), активное сканирование API по контракту: без токена
(74 адреса, 119 правил) и от имени client, engineer, admin; пассивный baseline двух кабинетов. Сводки —
`docs/reviews/security/<дата-прогон>/summary.md`.

| Прогон | Образ | API High / Medium / Low | Веб High / Medium / Low | Итог |
|---|---|---|---|---|
| 1 — до исправлений | `7758f48` | 0 / 0 / 3 (ZAP-1: 500 на `?search=%00`) | 0 / 4 / 10 (ZAP-2: clickjacking, CSP без `frame-ancestors`, nosniff, COOP/CORP, Permissions-Policy) | 0 High; 2 находки S3 |
| 2 — после ZAP-1, ZAP-2 | `876a662` | 0 / 0 / 0 | 0 / 0 / 2 (COEP) | PASS |
| 3 — итоговый, после ревью | `079577e` | 0 / 0 / 0 | 0 / 0 / 2 (COEP) | PASS — «0 критичных» |

Информационные сообщения (ответы 4xx на атакующие запросы, «Non-Storable Content» — `no-store` на `/v1`,
«Modern Web Application») — ожидаемое поведение, не находки.

## Пентест «чёрный ящик»

Независимая агент-сессия (ADR 0029 п. 2) не состоялась: её остановил классификатор безопасности на
первом ответе, до подъёма стенда; повторно не запускалась (ADR 0029 п. 21). Ручная проверка по
темам пентеста закрыта автоматическими проверками: RBAC и IDOR — [Д1][Д2], токены и сессии —
[Д3][Д4], SMS — [Д5], инъекции и XSS — [Д6][Д7], заголовки и Swagger — [Д8], активные проходы ZAP от
имени каждой роли. Отклонение от чек-листа: пентест людьми или отдельной сессией — внешний, после
релиза по решению владельца (глава 28).

## Находки

Уровень — по базовой оценке CVSS v3.1 (ADR 0029 п. 3): ≥ 7,0 — S2 (S1 — блокер), 4,0–6,9 — S3, < 4,0 — S4.
Критичных (S1/S2) открытых нет.

| № | Находка | Источник | CVSS v3.1 | Уровень | Статус |
|---|---|---|---|---|---|
| Ф1 | Вход сотрудника запирается неудачами с любого адреса (#102, B1 №3) | глава 23, B1 | 5,3 `AV:N/AC:L/PR:N/UI:N/S:U/C:N/I:N/A:L` | S3 | исправлено: лимит «номер + IP», потолок на номер, сброс пароля снимает [Д4] |
| Ф2 | Access-токен действует до 15 мин после выхода и сброса пароля (#102, B1 №4) | глава 23, B1 | 4,8 `AV:N/AC:H/PR:N/UI:N/S:U/C:L/I:L/A:N` | S3 | исправлено: `sessions_revoked_at`, `jti` выхода [Д4] |
| Ф3 | Пароль сотрудника — только длина 12 (#102, B1 №5) | глава 23, B1 | 4,8 `AV:N/AC:H/PR:N/UI:N/S:U/C:L/I:L/A:N` | S3 | исправлено: zxcvbn ≥ 3 [Д4] |
| Ф4 | SMS-код уходит заблокированному клиенту — платная рассылка (#103) | глава 23, B1 | 5,3 `AV:N/AC:L/PR:N/UI:N/S:U/C:N/I:N/A:L` | S3 | исправлено: тот же ответ без кода и SMS [Д5] |
| Ф5 | Привязка Telegram без доказательства владения | ADR 0013, 0021 | 5,4 `AV:N/AC:L/PR:L/UI:N/S:U/C:N/I:L/A:L` | S3 | исправлено: подпись Login Widget |
| Ф6 | ПД в журнале доступа: телефон в строке поиска, push-токен в пути | аудит главы | 2,3 `AV:L/AC:L/PR:H/UI:N/S:U/C:L/I:N/A:N` | S4 | исправлено: свой журнал, `PiiFilter` [Д11] |
| Ф7 | Swagger и схема открыты в production | аудит главы | 5,3 `AV:N/AC:L/PR:N/UI:N/S:U/C:L/I:N/A:N` | S3 | исправлено [Д8] |
| Ф8 | Нет заголовков безопасности в ответах API | аудит главы | 4,3 `AV:N/AC:L/PR:N/UI:R/S:U/C:N/I:L/A:N` | S3 | исправлено [Д8] |
| Ф9 | Процесс в контейнере — root | аудит главы | 3,9 `AV:L/AC:H/PR:H/UI:N/S:U/C:L/I:L/A:L` | S4 | исправлено: `USER 10001` |
| Ф10 | HTML в статьях базы знаний принимался (контракт — «без HTML») | аудит главы | 4,8 `AV:N/AC:L/PR:H/UI:R/S:C/C:L/I:L/A:N` | S3 | исправлено: 422 [Д7] |
| Ф11 | starlette 0.46.2 — 7 CVE (наивысшая CVE-2025-62727, Range) | pip-audit | 7,5 `AV:N/AC:L/PR:N/UI:N/S:U/C:N/I:N/A:H` | S2 | исправлено: 1.8.0; уязвимые части (формы, `FileResponse`, `StaticFiles`) приложение не использует |
| Ф12 | mako 1.4.1 — PYSEC-2026-4243 | osv-scanner | 6,5 (OSV) | S3 | исправлено: 1.4.2 |
| Ф13 | pytest 8.4.2 — CVE-2025-71176 (только разработка) | pip-audit | — (локальная, dev) | S4 | исправлено: 9.1 |
| Ф14 | ZAP-1: NUL в строке запроса — 500 | ZAP, прогон 1 | 4,3 `AV:N/AC:L/PR:L/UI:N/S:U/C:N/I:N/A:L` | S3 | исправлено: 422 / 404 [Д16] |
| Ф15 | ZAP-2: кабинеты без защиты от clickjacking | ZAP, прогон 1 | 4,3 `AV:N/AC:L/PR:N/UI:R/S:U/C:N/I:L/A:N` | S3 | исправлено: `SECURITY_HEADERS` |
| Ф16 | COEP не задан (ZAP 90004) | ZAP, прогоны 2–3 | — (Low по ZAP) | S4 | принято: `require-corp` блокировал бы вложения S3; кросс-доменная изоляция не нужна |
| Ф17 | Уязвимые пакеты инструментов разработки (Prism, Spectral: 12 High по npm audit) | npm audit | — (не в сборке) | S4 | принято: работают только в CI на своей спецификации; обновления — dependabot |
| Ф18 | Нет анонимизации ПД после отзыва согласия (99-З ст. 10) | ADR 0013 п. 9 | — (соответствие) | — | реализовано: worker ПД, миграции `0016`–`0017` |

Итого: S1 — 0; S2 — 1 (Ф11, закрыта); S3 — 11 (закрыты); S4 — 5 (3 закрыты, 2 приняты с обоснованием).

## Отложено
- HSTS, CSP заголовком, `frame-ancestors`, TLS — nginx (глава 26); повтор ZAP на сервере (глава 26).
- Бот Telegram и его токен, юридический текст политики, основание трансграничной передачи — владелец
  (глава 27); внешний пентест — после релиза по решению владельца (глава 28).
- FastAPI 0.137+ меняет структуру маршрутов (`_IncludedRouter`) — обновление вместе с тестами RBAC,
  которые обходят `app.routes` (dependabot предложит; ADR 0029 п. 9).
