# Глава 25 — Тестирование безопасности. Отчёт

Issue #120, ветка `feature/120-security-testing`, PR #121, ADR 0029 (grilling Q1–Q12), глоссарий v1.17
(«Анонимизация», «Срок хранения данных»), RBAC-06. Сжатые итоги сканирования — `docs/reviews/security/`,
сырые отчёты ZAP — артефакт `zap-results` workflow `security.yml` (ADR 0029 п. 7). Приложение к
пояснительной записке — `docs/Prilozhenie_Glava25_Security.docx` (ADR 0029 п. 20).

## Шаги чек-листа
| Шаг | Статус | Где |
|---|---|---|
| Чек-лист OWASP Top 10 по каждому сервису | PASS | таблица «OWASP Top 10:2025 × сервис» ниже; для API — сверка с API Security Top 10:2023, для мобильного приложения — сокращённый MASVS |
| Тест IDOR — чужой тикет/авто подменой ID | PASS | `test_idor_matrix.py` (9 операций `/vehicles/{id}/*` × 5 участников × активное/удалённое авто, 90 клеток, проверен мутацией), `test_ticket_security.py::test_object_level_matrix`; E2E-33 |
| Защита от SQL-инъекций и XSS в тикетах/чате | PASS | `test_injection.py` (12 нагрузок в описании, чате, статьях, поиске и фильтрах), Playwright — XSS в чате инженера не исполняется, Flutter — `MarkdownBody` без HTML и картинок; HTML в статьях — 422 |
| Автоматизированная проверка RBAC-матрицы по каждому эндпоинту | PASS | `test_rbac_matrix.py`: 63 защищённые операции контракта × 3 роли; роли — `x-required-roles`, их соответствие RBAC-матрице — `test_openapi_contract.py` |
| Пентест или сканирование (OWASP ZAP) | ZAP_STATUS | ZAP 2.17.0: API без токена и от client, engineer, admin + baseline двух кабинетов (`security.yml`, `scripts/zap_scan.sh`); пентест «чёрный ящик» — `docs/reviews/security/BLACKBOX_25.md` |
| Все уязвимости классифицированы, критичные закрыты | FINDINGS_STATUS | таблица «Находки» ниже: CVSS v3.1 → S1–S4 (ADR 0029 п. 3) |
| Повторное сканирование — 0 критичных | RESCAN_STATUS | «ZAP: до и после» ниже |

**DoD:** отчёт по безопасности оформлен и приложен к пояснительной записке: DOD_STATUS.

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
клиента). В клетке — PASS, N/A или номер находки; доказательства — [Д1]…[Д15] ниже.

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

ZAP_SECTION

BLACKBOX_SECTION

FINDINGS_SECTION

## Отложено
- HSTS, CSP заголовком, `frame-ancestors`, TLS — nginx (глава 26); повтор ZAP на сервере (глава 26).
- Бот Telegram и его токен, юридический текст политики, основание трансграничной передачи — владелец
  (глава 27); внешний пентест — после релиза по решению владельца (глава 28).
- FastAPI 0.137+ меняет структуру маршрутов (`_IncludedRouter`) — обновление вместе с тестами RBAC,
  которые обходят `app.routes` (dependabot предложит; ADR 0029 п. 9).
