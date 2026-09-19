-- Уведомления + Web Push подписки + presence-статусы (Этап 6).
--
-- Идемпотентно: CREATE TABLE IF NOT EXISTS + CREATE INDEX IF NOT EXISTS.

CREATE TABLE IF NOT EXISTS notification (
    id           SERIAL PRIMARY KEY,
    user_id      INTEGER NOT NULL REFERENCES system_users(id) ON DELETE CASCADE,
    kind         VARCHAR(48) NOT NULL,
    section      VARCHAR(16) NOT NULL,  -- deals / tasks / chat
    entity_type  VARCHAR(16) NULL,
    entity_id    INTEGER NULL,
    payload      JSONB NOT NULL DEFAULT '{}'::jsonb,
    read_at      TIMESTAMP NULL,
    created_at   TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);
-- Быстрая выборка непрочитанных для юзера — bell-иконка в шапке.
CREATE INDEX IF NOT EXISTS idx_notification_user_unread
    ON notification (user_id, read_at) WHERE read_at IS NULL;
-- Bulk-выборка по секции для счётчиков красных точек.
CREATE INDEX IF NOT EXISTS idx_notification_user_section_unread
    ON notification (user_id, section) WHERE read_at IS NULL;
-- Хронологическая пагинация в панели уведомлений.
CREATE INDEX IF NOT EXISTS idx_notification_user_created
    ON notification (user_id, created_at DESC);


CREATE TABLE IF NOT EXISTS web_push_subscription (
    id             SERIAL PRIMARY KEY,
    user_id        INTEGER NOT NULL REFERENCES system_users(id) ON DELETE CASCADE,
    endpoint       VARCHAR(1024) NOT NULL,
    keys           JSONB NOT NULL,
    user_agent     VARCHAR(500) NULL,
    created_at     TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    last_used_at   TIMESTAMP NULL,
    CONSTRAINT uq_web_push_endpoint UNIQUE (endpoint)
);
CREATE INDEX IF NOT EXISTS idx_web_push_user
    ON web_push_subscription (user_id);


CREATE TABLE IF NOT EXISTS user_presence (
    user_id             INTEGER PRIMARY KEY REFERENCES system_users(id) ON DELETE CASCADE,
    last_heartbeat_at   TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    current_section     VARCHAR(32) NULL
);
