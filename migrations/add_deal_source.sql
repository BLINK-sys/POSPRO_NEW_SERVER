-- Справочник «Источник сделки» + FK в deal + FK в crm_ingest_source для
-- автопростановки. Обнуляем старые deal.source (пользователь попросил
-- чистый справочник, старые enum-значения не мигрируем).

CREATE TABLE IF NOT EXISTS deal_source (
    id SERIAL PRIMARY KEY,
    name VARCHAR(128) NOT NULL UNIQUE,
    color VARCHAR(9),
    sort_order INTEGER NOT NULL DEFAULT 0,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW()
);

ALTER TABLE deal
    ADD COLUMN IF NOT EXISTS source_id INTEGER
    REFERENCES deal_source(id) ON DELETE SET NULL;

CREATE INDEX IF NOT EXISTS idx_deal_source_id ON deal(source_id);

ALTER TABLE crm_ingest_source
    ADD COLUMN IF NOT EXISTS default_deal_source_id INTEGER
    REFERENCES deal_source(id) ON DELETE SET NULL;

UPDATE deal SET source = NULL WHERE source IS NOT NULL;
