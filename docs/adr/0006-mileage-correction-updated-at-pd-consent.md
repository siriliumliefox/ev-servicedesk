# 0006. Корректировка пробега, updated_at в БД, история согласий ПД

**Статус:** Принято, 2026-10-10 (владелец проекта, Issue #15). Частично заменяет ADR 0003 (п. 6, 9)
и ADR 0005 (п. 4, хранение согласия).

## Контекст
Техдолг главы 2, зафиксированный в ADR 0003 и 0005:
- ошибочно введённый пробег нельзя исправить вниз даже админу (`vehicle_guard`);
- `updated_at` обновлялся только ORM (`onupdate`), прямые SQL-UPDATE его не трогали;
- согласие на обработку ПД — две колонки `app_user.pd_consent_at` / `pd_policy_version`:
  нет истории редакций и факта отзыва (Закон РБ № 99-З, ст. 5, 10).

## Варианты
- **Пробег:** флаг «admin override» в `vehicle` / отключение триггера на сессию /
  append-only журнал корректировок, через который единственно возможно уменьшение.
- **updated_at:** только ORM / триггер БД.
- **Согласие:** колонки в `app_user` / отдельная таблица истории.

## Решение
1. **`vehicle_mileage_correction`** — append-only журнал (`old_mileage`, `new_mileage`, `reason`,
   `corrected_by_user_id`, `created_at`). Уменьшение пробега = INSERT строки:
   - `BEFORE INSERT`: автор — `admin` (иначе `mileage_correction_admin_only`); `old_mileage` равен
     текущему пробегу, строка `vehicle` блокируется `FOR UPDATE` (иначе `mileage_correction_stale`);
     `created_at := now()`;
   - `AFTER INSERT`: `UPDATE vehicle SET mileage = new_mileage`;
   - `vehicle_guard` v2 пропускает уменьшение, только если в **той же транзакции** есть корректировка
     с теми же `old/new` (`created_at = now()` — время начала транзакции). Прямой UPDATE вниз
     по-прежнему запрещён всем (`vehicle_mileage_monotonic`);
   - UPDATE/DELETE журнала запрещены (`vehicle_mileage_correction_append_only`).
   API: `POST /vehicles/{id}/mileage-corrections` (`correctVehicleMileage`, только admin, RBAC-02);
   `expected_current_mileage` ↔ `old_mileage`, расхождение → `409`.
2. **`updated_at`** — триггер `trg_set_updated_at` (функция `set_updated_at`) на каждой таблице
   с `updated_at`; значение перезаписывается даже при явной передаче. Полноту списка проверяет
   `test_every_updated_at_table_has_trigger`. ORM `onupdate` оставлен (значение в сессии), но источник
   истины — БД.
3. **`pd_consent`** — история согласий: `policy_version`, `given_at`, `withdrawn_at`, `created_at`,
   `updated_at`. Не более одного действующего согласия (`uq_pd_consent_active` WHERE
   `withdrawn_at IS NULL`). Триггер `pd_consent_guard` запрещает DELETE и любой UPDATE, кроме
   однократной установки `withdrawn_at` (`pd_consent_withdraw_only`): строка — доказательство
   согласия и не может быть переписана. FK на `app_user` — RESTRICT; после анонимизации история
   сохраняется. Миграция `0004` переносит существующие согласия и удаляет колонки из `app_user`.
   API: `VerifyCodeRequest.pd_policy_version` (без действующего согласия — `422 PD_CONSENT_REQUIRED`),
   `DELETE /auth/pd-consent` (`withdrawPdConsent`, client): отзыв, отзыв refresh-токенов,
   постановка в очередь анонимизации; повторный отзыв — `409 PD_CONSENT_NOT_ACTIVE`.
   `UserPublic.phone` — nullable (анонимизированный пользователь).

## Последствия
- Миграция `0004`; downgrade возвращает колонки и только действующее согласие (история теряется).
- RBAC-матрица: +2 действия (RBAC-02) — изменение baseline требований, нужен новый тег версии
  (ADR 0002).
- Сервисный слой (Главы 10, 11) переводит ошибки ограничений в HTTP: `mileage_correction_stale` → 409,
  `pd_consent_withdraw_only`/`uq_pd_consent_active` → 409; роль проверяется и в API (403), триггер —
  последняя линия защиты.
- Анонимизация в течение 15 дней после отзыва — фоновая задача (Глава 10/15). Срок сверен с текстом
  закона (99-З, ст. 10 п. 2: «в пятнадцатидневный срок» — прекратить обработку, удалить, уведомить
  субъекта); трассировка — [`docs/compliance/PD_99Z_CHECKLIST.md`](../compliance/PD_99Z_CHECKLIST.md).
  ASSUMPTION: формулировки, правовое основание и юридическая полнота не проверены юристом (как в ADR 0005);
  VIN при анонимизации не удаляется и уведомление субъекта не спроектировано (чек-лист, п. 14).
- Анонимизация VIN по-прежнему требует исключения в `vehicle_guard` (техдолг ADR 0005 остаётся).
