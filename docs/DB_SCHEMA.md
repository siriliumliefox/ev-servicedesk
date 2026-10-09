# Схема БД — покрытие требований (Глава 2)

Источник истины: `backend/app/models` + `backend/alembic/versions` (ADR 0003).
Артефакты (генерируются, руками не правятся): [`EV_ServiceDesk_Glava2_DDL.sql`](EV_ServiceDesk_Glava2_DDL.sql),
[`ERD_EV_ServiceDesk_Glava2.mermaid`](ERD_EV_ServiceDesk_Glava2.mermaid). Тесты — `backend/tests/db/`.

## Сущности MASTER_CHECKLIST → таблицы

| Сущность | Таблицы |
|---|---|
| User | `app_user`, `refresh_token`, `pd_consent` |
| Vehicle | `vehicle`, `vehicle_model`, `vehicle_mileage_correction` |
| Aggregate | `aggregate_type`, `vehicle_aggregate_status`, `maintenance_record` |
| MaintenanceRegulation | `maintenance_regulation` |
| Ticket | `ticket`, `ticket_attachment` |
| TicketMessage | `ticket_message` |
| KnowledgeArticle | `knowledge_article`, `decision_tree_node` |
| Notification | `notification`, `notification_recipient`, `push_token`, `notification_delivery` |
| FirmwareRelease | `firmware_release` |

Итого 20 таблиц, 6 ENUM; триггеры: `trg_vehicle_guard`, `trg_set_updated_at` (на каждой таблице с `updated_at`), корректировка пробега и защита `pd_consent` (ADR 0006). Связи 1:N — все FK; M:N —
`notification_recipient` (notification × user), `notification_delivery` (notification × push_token).

## Бэклог baseline v1 → данные

| ID | Данные в схеме |
|---|---|
| C-01, X-02, N-06 | `app_user.phone` (E.164, UNIQUE); SMS-коды — Redis (ADR 0005) |
| C-02, X-05 | `vehicle.vin` (CHECK, частичный UNIQUE), `vehicle_model` |
| C-03 | `vehicle.mileage`, `maintenance_record`, `vehicle_mileage_correction` (ADR 0006) |
| C-04, C-05 | `vehicle_aggregate_status`, `maintenance_regulation` (расчёт — Глава 5) |
| C-06 | `knowledge_article.vehicle_model_id`, `.firmware_release_id`, `vehicle.current_firmware_release_id` |
| C-07 | `decision_tree_node`, `ticket.source_article_id`, `ticket.source_node_id` |
| C-08, X-03 | `ticket`, `ticket_attachment` (object_key, ADR 0004) |
| C-09 | `ticket_message`; история — `ticket` по `vehicle.user_id` |
| C-10, C-11, C-14, A-03 | `notification` (type, таргетинг по модели), `firmware_release`, `push_token` |
| C-12 | `vehicle.user_id` 1:N |
| C-13 | `notification_recipient.read_at` |
| C-15, X-06 | `app_user.telegram_id` (UNIQUE) |
| E-01 | `ticket.status`, `ticket.sla_due_at`, `ticket.category`, индекс `(status, sla_due_at)` |
| E-02 | `ticket.status`, `resolved_at` (CHECK согласованности) |
| E-03 | `knowledge_article` |
| E-04, N-09 | `ticket.vehicle_id` → `vehicle`; `ticket.firmware_release_id` (снимок прошивки) |
| E-05 | `vehicle_aggregate_status` + `maintenance_record.performed_by_user_id` |
| E-06, N-01…N-05 | UI, данных в БД не требуют |
| A-01 | `maintenance_regulation` (версии через `is_archived`) |
| A-02 | `knowledge_article`, `decision_tree_node` |
| A-04 | `app_user.role`, `is_active` |
| A-05 | `ticket.created_at`, `first_response_at`, `resolved_at` |
| A-06 | `ticket` × `vehicle_model`; конверсия — `maintenance_record.ticket_id`, `notification_recipient` |
| A-07 | `aggregate_type` (seed — миграция 0002) |
| X-01 | `app_user.role`; object-level — см. ниже |
| X-04, N-08 | `password_hash`, `refresh_token.token_hash` (SHA-256) |
| N-07 | `pd_consent` (история, отзыв), `app_user.anonymized_at` (ADR 0005, 0006) |
| N-10 | `maintenance_regulation` + `vehicle_aggregate_status` + `notification` (type = maintenance) |

## Ревью «по ролям» (сверено с `openapi.yaml` 1.0.0-rc3)

| Роль / экран | Поля OpenAPI | Источник в БД |
|---|---|---|
| client: список/карточка авто | `Vehicle.vin, mileage, is_active, vehicle_model, current_firmware_version, created_at` | `vehicle`, `vehicle_model`, `firmware_release.version`; `is_active = deleted_at IS NULL` |
| client: схема агрегатов | `AggregateStatus.*` | `vehicle_aggregate_status`, `aggregate_type`, `maintenance_regulation` (статус/процент — расчёт) |
| client: история ТО | `MaintenanceRecord.*` | `maintenance_record`, `aggregate_type.code`, `app_user` |
| client: обучение / дерево | `KnowledgeArticle.*`, `DecisionTreeNode.*` | `knowledge_article`, `decision_tree_node` |
| client: тикет + чат | `TicketCreateRequest.*`, `TicketDetail.*`, `TicketMessage.*` | `ticket` (`description`), `ticket_message`, `ticket_attachment` |
| client: центр уведомлений | `NotificationListItem.read_at` | `notification`, `notification_recipient` |
| engineer: канбан | `Ticket.status, category, sla_due_at, is_overdue, assigned_engineer_id` | `ticket` (`is_overdue` — расчёт) |
| engineer: карточка авто из тикета | `TicketDetail.vehicle_context` | `ticket.vehicle_id` → `vehicle`, `vehicle_aggregate_status` |
| engineer: замена агрегата | `AggregateReplaceRequest.*` | `vehicle_aggregate_status` + `maintenance_record` |
| admin: регламенты / агрегаты | `MaintenanceRegulation.*`, `AggregateType.*` | `maintenance_regulation`, `aggregate_type` |
| admin: прошивки / рассылки | `FirmwareRelease.*`, `Notification.*` | `firmware_release`, `notification` |
| admin: пользователи | `UserPublic.*` | `app_user` |
| admin: корректировка пробега | `MileageCorrectionRequest.*` | `vehicle_mileage_correction`, `vehicle.mileage` |
| client: согласие/отзыв ПД | `VerifyCodeRequest.pd_policy_version`, `withdrawPdConsent` | `pd_consent` |
| admin: аналитика | (Глава 16) | `ticket.created_at/resolved_at`, `notification_delivery.opened_at` |

## Object-level доступ (RBAC_MATRIX, RBAC-01)

| Объект | Правило | Опора в схеме |
|---|---|---|
| vehicle | client — свои; engineer — из назначенного тикета (RBAC-01); admin — все | `vehicle.user_id` (неизменяем), `ticket(vehicle_id, assigned_engineer_id)` |
| ticket | client — тикеты своих авто; engineer — все/назначенные | `ticket.vehicle_id → vehicle.user_id`, `assigned_engineer_id` |
| attachment | как у тикета; публичных ссылок нет | `ticket_attachment.ticket_id`, `object_key` (ADR 0004) |

Реализация проверок — сервисный слой глав 11–13; здесь доказано только наличие данных
(`test_rbac01_engineer_vehicle_access_via_assigned_ticket`).

## Инварианты → тесты

| Инвариант | Ограничение | Тест (`backend/tests/db/`) |
|---|---|---|
| VIN — 17 символов ISO 3779 | `ck_vehicle_vin_format` | `test_vin_format_rejected` |
| Один активный авто на VIN | `uq_vehicle_vin_active` | `test_vin_unique_among_active_vehicles` |
| Смена владельца не ломает историю ТО | soft-delete + новая запись | `test_owner_change_keeps_maintenance_history` |
| VIN/владелец/модель неизменяемы | `trg_vehicle_guard` | `test_vehicle_identity_is_immutable` |
| Пробег ≥ 0 и не уменьшается (409) | CHECK + `trg_vehicle_guard` | `test_mileage_cannot_*`, `test_conditional_mileage_update_reports_conflict` |
| Уменьшение пробега — только admin через журнал, с проверкой актуальности | триггеры `mileage_correction_*`, `vehicle_guard` v2 | `test_admin_correction_lowers_mileage_with_audit`, `test_only_admin_can_correct`, `test_stale_correction_rejected`, `test_direct_decrease_still_forbidden_even_for_admin` |
| Журнал корректировок append-only | `vehicle_mileage_correction_append_only` | `test_correction_log_is_append_only` |
| `updated_at` выставляет БД при любом UPDATE | `trg_set_updated_at` | `test_every_updated_at_table_has_trigger`, `test_raw_sql_update_bumps_updated_at` |
| Одно действующее согласие ПД; доказательство неизменно, отзыв однократен | `uq_pd_consent_active`, `pd_consent_withdraw_only` | `test_single_active_consent_and_history`, `test_consent_evidence_is_immutable`, `test_consent_withdrawal_is_final` |
| Телефон E.164, уникален | `ck_app_user_phone_e164`, `uq_app_user_phone` | `test_phone_must_be_e164`, `test_phone_unique` |
| Одна запись статуса на (авто, агрегат) | `uq_vehicle_aggregate_status_*` | `test_one_status_per_vehicle_and_aggregate` |
| Один активный регламент на (модель, агрегат) | `uq_maintenance_regulation_active` | `test_regulation_interval_rules` |
| Атомарный claim тикета | условный UPDATE + row lock | `test_concurrent_claim_has_single_winner` |
| Только хэши секретов | `ck_refresh_token_token_hash_sha256`, `ck_app_user_staff_password` | `test_refresh_token_stores_only_sha256`, `test_staff_requires_password_hash` |
| Вложение и сообщение — одного тикета | `fk_ticket_attachment_message_same_ticket` | `test_attachment_message_must_belong_to_same_ticket` |
| ORM ≡ миграции; DDL/ERD синхронны | autogenerate, export-скрипты | `test_orm_matches_migrations`, `test_ddl_file_in_sync_with_migrations`, `test_erd_file_in_sync_with_models` |
