-- CRM модуль: Сделки (7 таблиц) + Задачи (4) + Чат (5) + сквозные
-- `entity_attachment` и `crm_ingest_source`. Всего 18 новых таблиц.
--
-- Идемпотентность: `CREATE TABLE IF NOT EXISTS`, `CREATE INDEX IF NOT EXISTS`,
-- `ON CONFLICT DO NOTHING`. Скрипт можно перезапускать без последствий.
--
-- Seed (дефолтная воронка, общий чат, internal-источники ingest) —
-- в `apply_crm_tables.py`, чтобы можно было подставить реальные id
-- (SERIAL) и добавить membership всех system_user'ов в общий чат.
--
-- См. `PosPro/Магазин PosPro/Доменные области/31 CRM и двумодовая навигация (планирование).md`
-- за полной картиной поля-по-полю.

-- ============================================================================
-- СДЕЛКИ
-- ============================================================================

CREATE TABLE IF NOT EXISTS deal_pipeline (
    id          SERIAL PRIMARY KEY,
    name        VARCHAR(128) NOT NULL,
    "order"     INTEGER NOT NULL DEFAULT 0,
    active      BOOLEAN NOT NULL DEFAULT true,
    created_at  TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at  TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS deal_stage (
    id           SERIAL PRIMARY KEY,
    pipeline_id  INTEGER NOT NULL REFERENCES deal_pipeline(id) ON DELETE CASCADE,
    name         VARCHAR(128) NOT NULL,
    color        VARCHAR(9) NOT NULL DEFAULT '#94a3b8',
    "order"      INTEGER NOT NULL DEFAULT 0,
    type         VARCHAR(16) NOT NULL DEFAULT 'normal',
    created_at   TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at   TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_deal_stage_pipeline_order
    ON deal_stage (pipeline_id, "order");

CREATE TABLE IF NOT EXISTS deal (
    id                    SERIAL PRIMARY KEY,
    name                  VARCHAR(255) NOT NULL,
    client_id             INTEGER NULL REFERENCES kp_client(id) ON DELETE SET NULL,
    responsible_user_id   INTEGER NULL REFERENCES system_users(id) ON DELETE SET NULL,
    pipeline_id           INTEGER NOT NULL REFERENCES deal_pipeline(id) ON DELETE RESTRICT,
    stage_id              INTEGER NOT NULL REFERENCES deal_stage(id) ON DELETE RESTRICT,
    amount                NUMERIC(14, 2) NULL,
    currency              VARCHAR(8) NOT NULL DEFAULT 'KZT',
    expected_close_at     TIMESTAMP NULL,
    priority              VARCHAR(16) NOT NULL DEFAULT 'normal',
    source                VARCHAR(32) NULL,
    status                VARCHAR(16) NOT NULL DEFAULT 'open',
    tags                  JSONB NOT NULL DEFAULT '[]'::jsonb,
    notes                 TEXT NULL,
    source_ref_type       VARCHAR(64) NULL,
    source_ref_id         VARCHAR(128) NULL,
    created_at            TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at            TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_deal_pipeline_stage_status
    ON deal (pipeline_id, stage_id, status);
CREATE INDEX IF NOT EXISTS idx_deal_responsible
    ON deal (responsible_user_id);
CREATE INDEX IF NOT EXISTS idx_deal_source_ref
    ON deal (source_ref_type, source_ref_id)
    WHERE source_ref_type IS NOT NULL AND source_ref_id IS NOT NULL;

CREATE TABLE IF NOT EXISTS deal_member (
    id        SERIAL PRIMARY KEY,
    deal_id   INTEGER NOT NULL REFERENCES deal(id) ON DELETE CASCADE,
    user_id   INTEGER NOT NULL REFERENCES system_users(id) ON DELETE CASCADE,
    role      VARCHAR(16) NOT NULL DEFAULT 'participant',
    added_at  TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_deal_member UNIQUE (deal_id, user_id)
);

CREATE TABLE IF NOT EXISTS deal_kp (
    id             SERIAL PRIMARY KEY,
    deal_id        INTEGER NOT NULL REFERENCES deal(id) ON DELETE CASCADE,
    kp_history_id  INTEGER NOT NULL REFERENCES kp_history(id) ON DELETE CASCADE,
    attached_at    TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    attached_by    INTEGER NULL REFERENCES system_users(id) ON DELETE SET NULL,
    CONSTRAINT uq_deal_kp UNIQUE (deal_id, kp_history_id)
);

CREATE TABLE IF NOT EXISTS deal_order (
    id           SERIAL PRIMARY KEY,
    deal_id      INTEGER NOT NULL REFERENCES deal(id) ON DELETE CASCADE,
    order_id     INTEGER NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
    attached_at  TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_deal_order UNIQUE (deal_id, order_id)
);

CREATE TABLE IF NOT EXISTS deal_activity (
    id          SERIAL PRIMARY KEY,
    deal_id     INTEGER NOT NULL REFERENCES deal(id) ON DELETE CASCADE,
    user_id     INTEGER NULL REFERENCES system_users(id) ON DELETE SET NULL,
    kind        VARCHAR(32) NOT NULL,
    payload     JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at  TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_deal_activity_deal_created
    ON deal_activity (deal_id, created_at DESC);

-- ============================================================================
-- ЗАДАЧИ
-- ============================================================================

CREATE TABLE IF NOT EXISTS task (
    id              SERIAL PRIMARY KEY,
    title           VARCHAR(255) NOT NULL,
    description     TEXT NULL,
    priority        VARCHAR(16) NOT NULL DEFAULT 'normal',
    status          VARCHAR(20) NOT NULL DEFAULT 'pending',
    creator_id      INTEGER NULL REFERENCES system_users(id) ON DELETE SET NULL,
    responsible_id  INTEGER NULL REFERENCES system_users(id) ON DELETE SET NULL,
    deal_id         INTEGER NULL REFERENCES deal(id) ON DELETE SET NULL,
    client_id       INTEGER NULL REFERENCES kp_client(id) ON DELETE SET NULL,
    started_at      TIMESTAMP NULL,
    due_at          TIMESTAMP NULL,
    completed_at    TIMESTAMP NULL,
    tags            JSONB NOT NULL DEFAULT '[]'::jsonb,
    created_at      TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at      TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_task_responsible_status
    ON task (responsible_id, status);
CREATE INDEX IF NOT EXISTS idx_task_deal
    ON task (deal_id)
    WHERE deal_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_task_due
    ON task (due_at)
    WHERE due_at IS NOT NULL AND status != 'done';

CREATE TABLE IF NOT EXISTS task_member (
    id        SERIAL PRIMARY KEY,
    task_id   INTEGER NOT NULL REFERENCES task(id) ON DELETE CASCADE,
    user_id   INTEGER NOT NULL REFERENCES system_users(id) ON DELETE CASCADE,
    role      VARCHAR(16) NOT NULL DEFAULT 'co-worker',
    added_at  TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_task_member UNIQUE (task_id, user_id)
);

CREATE TABLE IF NOT EXISTS task_checklist (
    id          SERIAL PRIMARY KEY,
    task_id     INTEGER NOT NULL REFERENCES task(id) ON DELETE CASCADE,
    text        VARCHAR(500) NOT NULL,
    done        BOOLEAN NOT NULL DEFAULT false,
    "order"     INTEGER NOT NULL DEFAULT 0,
    created_at  TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS task_activity (
    id          SERIAL PRIMARY KEY,
    task_id     INTEGER NOT NULL REFERENCES task(id) ON DELETE CASCADE,
    user_id     INTEGER NULL REFERENCES system_users(id) ON DELETE SET NULL,
    kind        VARCHAR(32) NOT NULL,
    payload     JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at  TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_task_activity_task_created
    ON task_activity (task_id, created_at DESC);

-- ============================================================================
-- ЧАТ
-- ============================================================================

CREATE TABLE IF NOT EXISTS chat_room (
    id                SERIAL PRIMARY KEY,
    kind              VARCHAR(16) NOT NULL,
    name              VARCHAR(255) NULL,
    related_deal_id   INTEGER NULL REFERENCES deal(id) ON DELETE CASCADE,
    related_task_id   INTEGER NULL REFERENCES task(id) ON DELETE CASCADE,
    created_at        TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at        TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS chat_member (
    id            SERIAL PRIMARY KEY,
    room_id       INTEGER NOT NULL REFERENCES chat_room(id) ON DELETE CASCADE,
    user_id       INTEGER NOT NULL REFERENCES system_users(id) ON DELETE CASCADE,
    joined_at     TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    last_read_at  TIMESTAMP NULL,
    CONSTRAINT uq_chat_member UNIQUE (room_id, user_id)
);
CREATE INDEX IF NOT EXISTS idx_chat_member_user_room
    ON chat_member (user_id, room_id);

CREATE TABLE IF NOT EXISTS chat_message (
    id           SERIAL PRIMARY KEY,
    room_id      INTEGER NOT NULL REFERENCES chat_room(id) ON DELETE CASCADE,
    author_id    INTEGER NULL REFERENCES system_users(id) ON DELETE SET NULL,
    text         TEXT NULL,
    reply_to_id  INTEGER NULL REFERENCES chat_message(id) ON DELETE SET NULL,
    created_at   TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    edited_at    TIMESTAMP NULL,
    deleted_at   TIMESTAMP NULL
);
CREATE INDEX IF NOT EXISTS idx_chat_message_room_created
    ON chat_message (room_id, created_at DESC);

CREATE TABLE IF NOT EXISTS chat_reaction (
    id          SERIAL PRIMARY KEY,
    message_id  INTEGER NOT NULL REFERENCES chat_message(id) ON DELETE CASCADE,
    user_id     INTEGER NOT NULL REFERENCES system_users(id) ON DELETE CASCADE,
    emoji       VARCHAR(16) NOT NULL,
    created_at  TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_chat_reaction UNIQUE (message_id, user_id, emoji)
);

CREATE TABLE IF NOT EXISTS chat_attachment (
    id          SERIAL PRIMARY KEY,
    message_id  INTEGER NOT NULL REFERENCES chat_message(id) ON DELETE CASCADE,
    file_url    VARCHAR(1024) NOT NULL,
    file_name   VARCHAR(255) NULL,
    file_size   BIGINT NULL,
    mime_type   VARCHAR(100) NULL,
    created_at  TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- ============================================================================
-- СКВОЗНЫЕ
-- ============================================================================

CREATE TABLE IF NOT EXISTS entity_attachment (
    id           SERIAL PRIMARY KEY,
    entity_type  VARCHAR(16) NOT NULL,
    entity_id    INTEGER NOT NULL,
    file_url     VARCHAR(1024) NOT NULL,
    file_name    VARCHAR(255) NULL,
    file_size    BIGINT NULL,
    mime_type    VARCHAR(100) NULL,
    uploaded_by  INTEGER NULL REFERENCES system_users(id) ON DELETE SET NULL,
    uploaded_at  TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_entity_attachment_lookup
    ON entity_attachment (entity_type, entity_id);

CREATE TABLE IF NOT EXISTS crm_ingest_source (
    id                    SERIAL PRIMARY KEY,
    kind                  VARCHAR(16) NOT NULL,
    source_key            VARCHAR(64) NULL,
    token                 VARCHAR(64) NULL,
    name                  VARCHAR(128) NOT NULL,
    pipeline_id           INTEGER NOT NULL REFERENCES deal_pipeline(id) ON DELETE RESTRICT,
    stage_id              INTEGER NOT NULL REFERENCES deal_stage(id) ON DELETE RESTRICT,
    title_template        TEXT NOT NULL,
    notes_template        TEXT NULL,
    priority              VARCHAR(16) NOT NULL DEFAULT 'normal',
    assignment_strategy   VARCHAR(16) NOT NULL DEFAULT 'unassigned',
    pool_user_ids         JSONB NOT NULL DEFAULT '[]'::jsonb,
    fixed_user_id         INTEGER NULL REFERENCES system_users(id) ON DELETE SET NULL,
    assignment_index      INTEGER NOT NULL DEFAULT 0,
    client_resolution     VARCHAR(24) NOT NULL DEFAULT 'none',
    dedupe_by_ref         BOOLEAN NOT NULL DEFAULT true,
    active                BOOLEAN NOT NULL DEFAULT true,
    last_used_at          TIMESTAMP NULL,
    request_count         INTEGER NOT NULL DEFAULT 0,
    created_by            INTEGER NULL REFERENCES system_users(id) ON DELETE SET NULL,
    created_at            TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at            TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT ck_crm_ingest_source_kind_identity CHECK (
        (kind = 'webhook' AND token IS NOT NULL AND source_key IS NULL)
        OR (kind = 'internal' AND source_key IS NOT NULL AND token IS NULL)
    )
);
-- Частичные уникальные индексы: token уникален среди webhook-строк,
-- source_key — среди internal. NULL-значения не участвуют.
CREATE UNIQUE INDEX IF NOT EXISTS uq_crm_ingest_source_token
    ON crm_ingest_source (token)
    WHERE token IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS uq_crm_ingest_source_source_key
    ON crm_ingest_source (source_key)
    WHERE source_key IS NOT NULL;
