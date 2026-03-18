CREATE TABLE IF NOT EXISTS kp_history (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL,
    user_role VARCHAR(20) NOT NULL DEFAULT 'admin',
    name VARCHAR(255) NOT NULL DEFAULT '',
    items JSONB NOT NULL DEFAULT '[]'::jsonb,
    settings JSONB NOT NULL DEFAULT '{}'::jsonb,
    total_amount DOUBLE PRECISION NOT NULL DEFAULT 0,
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX idx_kp_history_user ON kp_history (user_id, user_role);
