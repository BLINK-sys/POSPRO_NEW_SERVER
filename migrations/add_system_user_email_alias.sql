-- Таблица email-алиасов для system_users.
-- Нужна чтобы запоминать мапу «старый email (например из B24) → реальный
-- user_id» и при следующем импорте B24 не создавать дубль юзера, а
-- автоматически привязываться к существующему.
--
-- Используется в migrate_system_users.py при мерже и в
-- migrations/bitrix24/fetch_mapping.py при разрешении email'а.

CREATE TABLE IF NOT EXISTS system_user_email_alias (
    email      VARCHAR(255) PRIMARY KEY,
    user_id    INTEGER NOT NULL REFERENCES system_users(id) ON DELETE CASCADE,
    note       VARCHAR(500),
    created_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS ix_sue_alias_user ON system_user_email_alias(user_id);
