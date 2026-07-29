-- Таблицы для сервиса сбора данных 2GIS.
-- См. models/collector.py и Обсидиан «21 2GIS сбор данных».
--
-- Отличия от integration_* таблиц:
--   * task per-user (owner_id) → историей владеет админ, не система;
--   * задача — с параметрами (города, запросы, колонки), а не глобальная;
--   * файлы .xlsx физически на локалке, прод хранит только метаданные и
--     rel_path (относительный к collector-outputs-корню воркера).
--
-- Идёмпотентно: CREATE TABLE IF NOT EXISTS + ON CONFLICT DO NOTHING на
-- сингл-row для collector_worker.

CREATE TABLE IF NOT EXISTS collector_task (
    id                      SERIAL PRIMARY KEY,
    owner_id                INTEGER NOT NULL REFERENCES system_users(id) ON DELETE CASCADE,

    name                    VARCHAR(200) NOT NULL DEFAULT '',
    cities                  JSONB NOT NULL DEFAULT '[]'::jsonb,
    queries                 JSONB NOT NULL DEFAULT '[]'::jsonb,
    custom_url              TEXT NULL,

    keep_columns            JSONB NULL,
    drop_other_columns      BOOLEAN NOT NULL DEFAULT true,
    autosize_columns        BOOLEAN NOT NULL DEFAULT true,
    wrap_text               BOOLEAN NOT NULL DEFAULT false,
    networks_min_count      INTEGER NULL,
    sort_by_name            BOOLEAN NOT NULL DEFAULT false,

    max_records             INTEGER NULL,
    file_format             VARCHAR(10) NOT NULL DEFAULT 'xlsx',
    delay_min_ms            INTEGER NOT NULL DEFAULT 3000,
    delay_max_ms            INTEGER NOT NULL DEFAULT 5000,

    status                  VARCHAR(20) NOT NULL DEFAULT 'queued',
    phase                   VARCHAR(50) NULL,
    progress                JSONB NULL,
    log_excerpt             TEXT NULL,
    error                   TEXT NULL,

    created_at              TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    started_at              TIMESTAMP NULL,
    finished_at             TIMESTAMP NULL
);

CREATE INDEX IF NOT EXISTS idx_collector_task_owner       ON collector_task (owner_id);
CREATE INDEX IF NOT EXISTS idx_collector_task_status      ON collector_task (status);
CREATE INDEX IF NOT EXISTS idx_collector_task_created_at  ON collector_task (created_at DESC);

CREATE TABLE IF NOT EXISTS collector_file (
    id              SERIAL PRIMARY KEY,
    task_id         INTEGER NOT NULL REFERENCES collector_task(id) ON DELETE CASCADE,

    city            VARCHAR(80) NOT NULL,
    city_name       VARCHAR(200) NULL,
    query           VARCHAR(500) NOT NULL,
    url             TEXT NOT NULL,

    rel_path        TEXT NULL,
    filename        VARCHAR(300) NULL,

    rows            INTEGER NOT NULL DEFAULT 0,
    bytes           INTEGER NOT NULL DEFAULT 0,
    attempts        INTEGER NOT NULL DEFAULT 0,
    duration_sec    DOUBLE PRECISION NOT NULL DEFAULT 0,
    status          VARCHAR(20) NOT NULL DEFAULT 'failed',
    error           TEXT NULL,

    created_at      TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_collector_file_task ON collector_file (task_id);

CREATE TABLE IF NOT EXISTS collector_command (
    id              SERIAL PRIMARY KEY,
    task_id         INTEGER NOT NULL REFERENCES collector_task(id) ON DELETE CASCADE,
    command         VARCHAR(30) NOT NULL,
    created_at      TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    created_by      VARCHAR(255) NULL,
    consumed_at     TIMESTAMP NULL
);
CREATE INDEX IF NOT EXISTS idx_collector_command_task_pending
    ON collector_command (task_id) WHERE consumed_at IS NULL;

CREATE TABLE IF NOT EXISTS collector_worker (
    id                  SERIAL PRIMARY KEY,
    last_heartbeat_at   TIMESTAMP NULL,
    hostname            VARCHAR(200) NULL,
    updated_at          TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Единственная запись — сингл-row таблица для heartbeat.
INSERT INTO collector_worker (id, last_heartbeat_at, hostname)
VALUES (1, NULL, NULL)
ON CONFLICT (id) DO NOTHING;

-- Идёмпотентные ALTER'ы для расширения существующих таблиц (PG 9.6+).
-- Скрипт разбивается apply_collector_tables.py по ';' построчно, поэтому
-- не используем DO $$ ... $$ (там ';' внутри) — только плоские ALTER'ы.
ALTER TABLE collector_task ADD COLUMN IF NOT EXISTS name VARCHAR(200) NOT NULL DEFAULT '';
