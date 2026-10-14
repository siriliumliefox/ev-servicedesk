# Architecture Decision Records

Формат: `NNNN-kebab-title.md`, разделы: Статус, Контекст, Варианты, Решение, Последствия.

| ADR | Решение |
|---|---|
| [0001](0001-ai-workflow-and-sources-of-truth.md) | Рабочий процесс AI и источники истины |
| [0002](0002-requirements-baseline-owner-approval.md) | Baseline требований утверждает владелец проекта |
| [0003](0003-database-schema-conventions.md) | Соглашения схемы БД: ID, ENUM, soft-delete, ON DELETE, timestamps |
| [0004](0004-file-storage-object-keys.md) | Хранение файлов: ключ объекта S3 и метаданные |
| [0005](0005-auth-secrets-and-personal-data.md) | Секреты авторизации и персональные данные |
| [0006](0006-mileage-correction-updated-at-pd-consent.md) | Корректировка пробега, updated_at в БД, история согласий ПД |
| [0007](0007-api-contract-v1-freeze.md) | Контракт API v1: заморозка, правила и проверки |
| [0008](0008-ci-gate-environments-staging-server.md) | CI-гейт, защита веток, окружения local → staging → production, staging-сервер — глава 26 |
| [0009](0009-aggregate-status-thresholds.md) | Алгоритм «светофор»: глобальные пороги, худший из двух интервалов, точные границы |
| [0010](0010-design-tokens-source-of-truth.md) | Дизайн-токены: `design/tokens.json` — источник истины, бренд ETS AUTO, темы, Figma на Starter |
| [0011](0011-mobile-clickable-prototype-flutter.md) | Кликабельный прототип клиента — Flutter на фикстурах вместо Figma; навигация по ТЗ из 4 пунктов |
| [0012](0012-web-prototypes-react-fixtures.md) | Прототипы веб-кабинета инженера и админ-панели — React на фикстурах; SLA из `sla_due_at`, быстрые ответы из базы знаний, контракт v1 без изменений |
| [0013](0013-auth-service-implementation.md) | Auth Service: SMS через A1, JWT + ротация refresh, RBAC с deny by default, лимиты, «staging» = проверенный образ до главы 26 |
| [0014](0014-vehicle-service-implementation.md) | Vehicle Service: мок VIN-декодера за `VinDecoder`, конфликт VIN (два кода 409, восстановление своего авто), лимит добавления, доступ инженера по тикетам, история работ |
| [0015](0015-orm-relationships-explicit-loading.md) | ORM-связи только с явной загрузкой: `relationship(lazy="raise")` + `selectinload`, ответы API через `from_attributes`, производные поля — `column_property` |
| [0016](0016-aggregates-maintenance-service.md) | Aggregates & Maintenance Service: счётчик сбрасывает только замена агрегата, замена без регламента фиксируется, 409 при пробеге выше текущего, версии регламентов, сценарии главы 5 через сервис |
| [0017](0017-tickets-service.md) | Tickets Service: SLA — срок решения по категории, граф статусов и claim, доступ инженера (очередь + свои), чат на WebSocket + Redis, вложения через S3 (MinIO), контракт 1.4.0 аддитивно |
| [0018](0018-knowledge-base-service.md) | Knowledge Base Service: версия — опубликованная редакция со снимком, проверка тупиков дерева решений, публикация только валидного дерева, полнотекстовый поиск PostgreSQL, эскалация с версией статьи, контракт 1.5.0 |
| [0019](0019-notifications-service.md) | Notifications Service: исходящая очередь в БД + worker, снимок аудитории, прошивка по версии, напоминания о ТО за N км/дней, мягкий отзыв push-токенов, контракт 1.6.0 |
| [0020](0020-analytics-service.md) | Analytics Service: витрина фактов (materialized view) + `analytics-worker`, период по Минску, формулы A-05/A-06, `computed_at`, контракт 1.7.0 |
| [0021](0021-backend-integration.md) | Интеграция backend: стек из образа-кандидата, сверка ответов с OpenAPI вместо Pact, тег Users, право на уведомление при отправке, тестовые номера SMS, аудит целостности |
| [0022](0022-mobile-client-skeleton.md) | Мобильный клиент: HTTP-репозиторий вместо фикстур, refresh одним запросом без повторов, E2E на уровне API в CI и UI локально, Android только сборкой |
| [0023](0023-mobile-aggregate-scheme.md) | Схема агрегатов в мобильном клиенте: контур в SVG, замена и работа различаются в истории ТО (контракт 1.9.0), сверка статусов на 5 тестовых авто |
| [0024](0024-mobile-learning-tickets-notifications.md) | Мобильный клиент: обучение, дерево решений, тикеты с вложениями, чат по WebSocket, push (Android-эмулятор) и центр уведомлений; 3 прогона владельцем вместо разных тестировщиков |
| [0025](0025-engineer-web-cabinet.md) | Веб-кабинет инженера: API через тот же origin, токены в памяти и `sessionStorage`, канбан с перетаскиванием и опросом, конфликт взятия, `resolved_since` (контракт 1.10.0), E2E Playwright в CI, проверка владельцем в двух ролях |
| [0026](0026-admin-panel.md) | Админ-панель: вход только администратора, HTTP-слой `web-shared`, пользователи и сброс пароля (контракт 1.11.0), подтверждение аудитории публикации, E2E «регламент → статус клиента» и сверка дашборда с контрольным набором |
| [0027](0027-end-to-end-regression.md) | Сквозное E2E: матрица сценариев со стражем, P0 в CI (Playwright, Flutter на Android-эмуляторе), regression по опубликованному образу, RC1 принимает владелец |
