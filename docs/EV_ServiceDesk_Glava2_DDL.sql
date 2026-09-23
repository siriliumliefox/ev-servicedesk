-- EV-ServiceDesk — DDL (PostgreSQL)
-- Глава 2. Проектирование ER-схемы базы данных
-- Схема нормализована до 3НФ (см. комментарий у notification ниже — единственное
-- осознанное отступление от 1НФ: decision_tree_node.options хранит JSONB-массив
-- вариантов перехода вместо отдельной таблицы рёбер — решение MVP, Глава 2).

CREATE TYPE user_role AS ENUM ('client', 'engineer', 'admin');
CREATE TYPE ticket_category AS ENUM ('navigation', 'audio', 'sim', 'app_crash', 'maintenance');
CREATE TYPE ticket_status AS ENUM ('new', 'in_progress', 'waiting_vendor', 'resolved');
CREATE TYPE attachment_type AS ENUM ('photo', 'video');
CREATE TYPE kb_article_type AS ENUM ('guide', 'troubleshooting');
CREATE TYPE notification_type AS ENUM ('firmware', 'maintenance', 'news', 'promo');

-- Пользователи
CREATE TABLE "user" (
    id BIGSERIAL PRIMARY KEY,
    phone VARCHAR(20) NOT NULL,
    role user_role NOT NULL,
    telegram_id VARCHAR(50),
    password_hash VARCHAR(255),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    is_active BOOLEAN NOT NULL DEFAULT true,
    CONSTRAINT uq_user_phone UNIQUE (phone),
    CONSTRAINT uq_user_telegram UNIQUE (telegram_id)
);
CREATE INDEX idx_user_phone ON "user" (phone);

-- Справочник моделей авто
CREATE TABLE vehicle_model (
    id BIGSERIAL PRIMARY KEY,
    brand VARCHAR(100) NOT NULL,
    model VARCHAR(100) NOT NULL,
    trim VARCHAR(100) NOT NULL DEFAULT '',
    CONSTRAINT uq_vehicle_model UNIQUE (brand, model, trim)
);

-- Автомобили клиентов
CREATE TABLE vehicle (
    id BIGSERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL REFERENCES "user"(id),
    vehicle_model_id BIGINT NOT NULL REFERENCES vehicle_model(id),
    vin CHAR(17) NOT NULL,
    mileage INT NOT NULL DEFAULT 0,
    is_active BOOLEAN NOT NULL DEFAULT true, -- добавлено в Главе 3: soft-delete для CRUD Vehicle
    current_firmware_release_id BIGINT, -- добавлено в Главе 3 (шаг 5): FK ниже, после создания firmware_release
    CONSTRAINT uq_vehicle_vin UNIQUE (vin),
    CONSTRAINT chk_vehicle_mileage CHECK (mileage >= 0),
    CONSTRAINT chk_vehicle_vin_format CHECK (vin ~ '^[A-HJ-NPR-Z0-9]{17}$')
);
CREATE INDEX idx_vehicle_user ON vehicle (user_id);

-- Справочник типов агрегатов (расширяется через админ-панель)
CREATE TABLE aggregate_type (
    id BIGSERIAL PRIMARY KEY,
    code VARCHAR(50) NOT NULL,
    name VARCHAR(100) NOT NULL,
    CONSTRAINT uq_aggregate_type_code UNIQUE (code)
);

-- Регламенты ТО: модель + агрегат -> интервал
CREATE TABLE maintenance_regulation (
    id BIGSERIAL PRIMARY KEY,
    vehicle_model_id BIGINT NOT NULL REFERENCES vehicle_model(id),
    aggregate_type_id BIGINT NOT NULL REFERENCES aggregate_type(id),
    interval_km INT,
    interval_months INT,
    is_archived BOOLEAN NOT NULL DEFAULT false,
    CONSTRAINT chk_regulation_interval CHECK (interval_km IS NOT NULL OR interval_months IS NOT NULL)
);
-- частичный уникальный индекс: только одна активная версия регламента на пару модель+агрегат,
-- старые версии архивируются, а не удаляются (не ломает историю)
CREATE UNIQUE INDEX uq_regulation_active
    ON maintenance_regulation (vehicle_model_id, aggregate_type_id)
    WHERE is_archived = false;

-- Текущий статус агрегата на конкретном авто (кэш для быстрого расчёта "светофора")
CREATE TABLE vehicle_aggregate_status (
    id BIGSERIAL PRIMARY KEY,
    vehicle_id BIGINT NOT NULL REFERENCES vehicle(id),
    aggregate_type_id BIGINT NOT NULL REFERENCES aggregate_type(id),
    last_replaced_at DATE,
    last_replaced_mileage INT,
    CONSTRAINT uq_vehicle_aggregate UNIQUE (vehicle_id, aggregate_type_id)
);

-- История выполненных работ по авто
CREATE TABLE maintenance_record (
    id BIGSERIAL PRIMARY KEY,
    vehicle_id BIGINT NOT NULL REFERENCES vehicle(id),
    aggregate_type_id BIGINT REFERENCES aggregate_type(id),
    performed_by_user_id BIGINT REFERENCES "user"(id),
    performed_at DATE NOT NULL,
    mileage_at_service INT NOT NULL,
    description VARCHAR(255) -- добавлено в Главе 3: работы без привязки к конкретному агрегату
);
CREATE INDEX idx_maintenance_record_vehicle ON maintenance_record (vehicle_id);

-- Статьи базы знаний
CREATE TABLE knowledge_article (
    id BIGSERIAL PRIMARY KEY,
    vehicle_model_id BIGINT REFERENCES vehicle_model(id), -- NULL = общая статья
    article_type kb_article_type NOT NULL,
    version INT NOT NULL DEFAULT 1,
    is_published BOOLEAN NOT NULL DEFAULT false -- добавлено в Главе 3: черновик/публикация (админ-конструктор)
);

-- Узлы дерева решений (только для article_type = 'troubleshooting')
CREATE TABLE decision_tree_node (
    id BIGSERIAL PRIMARY KEY,
    article_id BIGINT NOT NULL REFERENCES knowledge_article(id),
    question_text TEXT NOT NULL,
    options JSONB NOT NULL DEFAULT '[]', -- [{label, next_node_id}], осознанное отступление от 1НФ
    is_root BOOLEAN NOT NULL DEFAULT false,
    is_escalation BOOLEAN NOT NULL DEFAULT false
);
CREATE INDEX idx_decision_tree_article ON decision_tree_node (article_id);
CREATE UNIQUE INDEX uq_decision_tree_root
    ON decision_tree_node (article_id)
    WHERE is_root = true;

-- Тикеты поддержки
CREATE TABLE ticket (
    id BIGSERIAL PRIMARY KEY,
    vehicle_id BIGINT NOT NULL REFERENCES vehicle(id),
    category ticket_category NOT NULL,
    status ticket_status NOT NULL DEFAULT 'new',
    assigned_engineer_id BIGINT REFERENCES "user"(id),
    sla_due_at TIMESTAMPTZ NOT NULL,
    source_article_id BIGINT REFERENCES knowledge_article(id),
    source_node_id BIGINT REFERENCES decision_tree_node(id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_ticket_vehicle ON ticket (vehicle_id);
CREATE INDEX idx_ticket_status ON ticket (status);
CREATE INDEX idx_ticket_engineer ON ticket (assigned_engineer_id);

-- Сообщения чата тикета
CREATE TABLE ticket_message (
    id BIGSERIAL PRIMARY KEY,
    ticket_id BIGINT NOT NULL REFERENCES ticket(id),
    author_id BIGINT NOT NULL REFERENCES "user"(id),
    body TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_ticket_message_ticket ON ticket_message (ticket_id);

-- Вложения (фото/видео)
CREATE TABLE ticket_attachment (
    id BIGSERIAL PRIMARY KEY,
    ticket_id BIGINT NOT NULL REFERENCES ticket(id),
    ticket_message_id BIGINT REFERENCES ticket_message(id), -- NULL = вложено при создании тикета
    file_url VARCHAR(500) NOT NULL,
    file_type attachment_type NOT NULL
);
CREATE INDEX idx_ticket_attachment_ticket ON ticket_attachment (ticket_id);

-- Релизы прошивок
CREATE TABLE firmware_release (
    id BIGSERIAL PRIMARY KEY,
    vehicle_model_id BIGINT NOT NULL REFERENCES vehicle_model(id),
    version VARCHAR(50) NOT NULL,
    released_at DATE NOT NULL,
    CONSTRAINT uq_firmware_release UNIQUE (vehicle_model_id, version)
);

-- Отложенный FK: vehicle ссылается на firmware_release, объявленный ниже по файлу
ALTER TABLE vehicle
    ADD CONSTRAINT fk_vehicle_firmware
    FOREIGN KEY (current_firmware_release_id) REFERENCES firmware_release(id);

-- Уведомления
-- ВАЖНО (3НФ): target_vehicle_model_id — единственный источник истины для таргетинга.
-- Заполняется явно ВСЕГДА, включая type = 'firmware' — НЕ выводится из
-- firmware_release_id при чтении, иначе транзитивная зависимость через
-- не-ключевое поле firmware_release_id. firmware_release_id — только ссылка
-- на контент (release notes), не источник таргетинга.
CREATE TABLE notification (
    id BIGSERIAL PRIMARY KEY,
    type notification_type NOT NULL,
    firmware_release_id BIGINT REFERENCES firmware_release(id),
    target_vehicle_model_id BIGINT REFERENCES vehicle_model(id), -- NULL = все модели
    message TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Push-токены устройств
CREATE TABLE push_token (
    id BIGSERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL REFERENCES "user"(id),
    token VARCHAR(255) NOT NULL,
    CONSTRAINT uq_push_token UNIQUE (token)
);
CREATE INDEX idx_push_token_user ON push_token (user_id);

-- Журнал доставки уведомлений (для аналитики открываемости, Глава 16)
CREATE TABLE notification_delivery (
    id BIGSERIAL PRIMARY KEY,
    notification_id BIGINT NOT NULL REFERENCES notification(id),
    push_token_id BIGINT NOT NULL REFERENCES push_token(id),
    delivered_at TIMESTAMPTZ,
    opened_at TIMESTAMPTZ,
    CONSTRAINT uq_notification_delivery UNIQUE (notification_id, push_token_id)
);
