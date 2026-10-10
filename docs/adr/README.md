# Architecture Decision Records

Формат: `NNNN-kebab-title.md`, разделы: Статус, Контекст, Варианты, Решение, Последствия.

| ADR | Решение |
|---|---|
| [0001](0001-ai-workflow-and-sources-of-truth.md) | Рабочий процесс AI и источники истины |
| [0002](0002-requirements-baseline-owner-approval.md) | Baseline требований утверждает владелец проекта |
| [0003](0003-database-schema-conventions.md) | Соглашения схемы БД: ID, ENUM, soft-delete, ON DELETE, timestamps |
| [0004](0004-file-storage-object-keys.md) | Хранение файлов: ключ объекта S3 и метаданные |
| [0005](0005-auth-secrets-and-personal-data.md) | Секреты авторизации и персональные данные |
| [0006](0006-mileage-correction-updated-at-pd-consent.md) | Корректировка пробега, updated_at в БД, история согласий ПД |
| [0007](0007-api-contract-v1-freeze.md) | Контракт API v1: заморозка, правила и проверки |
| [0008](0008-ci-gate-environments-staging-server.md) | CI-гейт, защита веток, окружения local → staging → production, staging-сервер — глава 26 |
| [0009](0009-aggregate-status-thresholds.md) | Алгоритм «светофор»: глобальные пороги, худший из двух интервалов, точные границы |
| [0010](0010-design-tokens-source-of-truth.md) | Дизайн-токены: `design/tokens.json` — источник истины, бренд ETS AUTO, темы, Figma на Starter |
| [0011](0011-mobile-clickable-prototype-flutter.md) | Кликабельный прототип клиента — Flutter на фикстурах вместо Figma; навигация по ТЗ из 4 пунктов |
| [0012](0012-web-prototypes-react-fixtures.md) | Прототипы веб-кабинета инженера и админ-панели — React на фикстурах; SLA из `sla_due_at`, быстрые ответы из базы знаний, контракт v1 без изменений |
