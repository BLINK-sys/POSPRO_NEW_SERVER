-- Таблица отслеживания импорта из Bitrix24.
-- См. models.b24_mirror.B24Mirror.

CREATE TABLE IF NOT EXISTS b24_mirror (
    id SERIAL PRIMARY KEY,
    entity_type VARCHAR(32) NOT NULL,
    b24_id VARCHAR(64) NOT NULL,
    pospro_id INTEGER NOT NULL,
    migration_tag VARCHAR(32) NOT NULL DEFAULT 'initial',
    imported_at TIMESTAMP NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_b24_mirror UNIQUE (entity_type, b24_id)
);

CREATE INDEX IF NOT EXISTS idx_b24_mirror_entity ON b24_mirror(entity_type);
CREATE INDEX IF NOT EXISTS idx_b24_mirror_pospro ON b24_mirror(entity_type, pospro_id);
