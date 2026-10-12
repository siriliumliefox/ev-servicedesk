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
