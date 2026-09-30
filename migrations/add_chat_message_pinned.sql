-- Пиннинг сообщений в чате.
-- Идемпотентная миграция.

ALTER TABLE chat_message
    ADD COLUMN IF NOT EXISTS pinned_at TIMESTAMP NULL;

ALTER TABLE chat_message
    ADD COLUMN IF NOT EXISTS pinned_by INTEGER NULL REFERENCES system_users(id) ON DELETE SET NULL;

-- Индекс для быстрой выборки закреплённых сообщений комнаты.
CREATE INDEX IF NOT EXISTS idx_chat_message_room_pinned
    ON chat_message (room_id, pinned_at DESC) WHERE pinned_at IS NOT NULL;
