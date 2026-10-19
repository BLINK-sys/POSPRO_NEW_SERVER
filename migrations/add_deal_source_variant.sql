-- Вариант (дочерний элемент) источника сделки. Иерархический справочник:
-- родитель — deal_source (OLX, Kaspi, 2GIS, ...), ребёнок —
-- deal_source_variant («Звонок поступил на номер: 87471260446 (OLX Астана).»
-- и т.п.). Создаётся вручную менеджером или автоматически B24-импортом
-- из поля SOURCE_DESCRIPTION. Позже сюда же будет писать SIP-телефония.
--
-- См. models.deal_source.DealSourceVariant.

CREATE TABLE IF NOT EXISTS deal_source_variant (
    id               SERIAL PRIMARY KEY,
    parent_source_id INTEGER NOT NULL REFERENCES deal_source(id) ON DELETE CASCADE,
    name             VARCHAR(500) NOT NULL,
    order_pos        INTEGER NOT NULL DEFAULT 0,
    created_at       TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at       TIMESTAMP NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_deal_source_variant UNIQUE (parent_source_id, name)
);

CREATE INDEX IF NOT EXISTS ix_dsv_parent ON deal_source_variant(parent_source_id);

ALTER TABLE deal
    ADD COLUMN IF NOT EXISTS source_variant_id INTEGER
    REFERENCES deal_source_variant(id) ON DELETE SET NULL;

CREATE INDEX IF NOT EXISTS ix_deal_source_variant_id ON deal(source_variant_id);
