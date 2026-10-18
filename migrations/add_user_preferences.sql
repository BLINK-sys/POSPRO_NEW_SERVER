-- Пользовательские настройки UI (key-value JSONB на юзера).
-- См. models.user_preference.UserPreference.

CREATE TABLE IF NOT EXISTS user_preferences (
    user_id INTEGER NOT NULL REFERENCES system_users(id) ON DELETE CASCADE,
    key VARCHAR(64) NOT NULL,
    value JSONB NOT NULL DEFAULT '{}'::jsonb,
    updated_at TIMESTAMP NOT NULL DEFAULT NOW(),
    PRIMARY KEY (user_id, key)
);
