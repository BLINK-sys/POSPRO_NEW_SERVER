-- Таблицы для автоматических выгрузок BIO / Equip с локального сервера.
-- Работают через pull-модель: воркер на локалке шлёт heartbeat и получает
-- команды от админки, прод хранит settings + историю runs + очередь команд.

CREATE TABLE IF NOT EXISTS integration_settings (
    id                  SERIAL PRIMARY KEY,
    type                VARCHAR(20) NOT NULL UNIQUE,
    enabled             BOOLEAN NOT NULL DEFAULT true,
    schedule_mode       VARCHAR(20) NOT NULL DEFAULT 'weekly',
    schedule_data       JSONB NOT NULL DEFAULT '{}'::jsonb,
    last_heartbeat_at   TIMESTAMP NULL,
    updated_at          TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS integration_run (
    id              SERIAL PRIMARY KEY,
    type            VARCHAR(20) NOT NULL,
    trigger         VARCHAR(20) NOT NULL,
    triggered_by    VARCHAR(255) NULL,
    started_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    finished_at     TIMESTAMP NULL,
    status          VARCHAR(20) NOT NULL DEFAULT 'running',
    phase           VARCHAR(50) NULL,
    progress        JSONB NULL,
    error           TEXT NULL,
    log_excerpt     TEXT NULL
);
CREATE INDEX IF NOT EXISTS idx_integration_run_type       ON integration_run (type);
CREATE INDEX IF NOT EXISTS idx_integration_run_status     ON integration_run (status);
CREATE INDEX IF NOT EXISTS idx_integration_run_started_at ON integration_run (started_at DESC);

CREATE TABLE IF NOT EXISTS integration_command (
    id              SERIAL PRIMARY KEY,
    type            VARCHAR(20) NOT NULL,
    command         VARCHAR(30) NOT NULL,
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    created_by      VARCHAR(255) NULL,
    consumed_at     TIMESTAMP NULL
);
CREATE INDEX IF NOT EXISTS idx_integration_command_type_pending
    ON integration_command (type) WHERE consumed_at IS NULL;

-- Стартовые записи settings для двух типов интеграций (без запуска —
-- воркер сам подхватит когда админ настроит расписание в UI).
INSERT INTO integration_settings (type, enabled, schedule_mode, schedule_data)
VALUES
    ('bio',   false, 'weekly', '{"days": [], "time": "03:00"}'::jsonb),
    ('equip', false, 'weekly', '{"days": [], "time": "04:00"}'::jsonb)
ON CONFLICT (type) DO NOTHING;
