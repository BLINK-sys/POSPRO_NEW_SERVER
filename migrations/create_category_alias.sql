-- Таблица «алиасов» категорий: маппинг «имя категории от поставщика →
-- наша канонич. категория». Даёт идемпотентность автовыгрузки bio/equip
-- (одно supplier-имя = одна и та же наша категория при повторных выгрузках)
-- и позволяет админу вручную объединять/переназначать через UI.
--
-- Уникальность по (source, parent_id, alias_name). source различает
-- поставщиков; parent_id даёт возможность иметь одинаковое имя в разных
-- ветках дерева (например «Ножи» под «Кухня» и «Ножи» под «Огород» —
-- разные категории). Case-insensitive проверку делает резолвер в SQL
-- через LOWER(alias_name), а храним значение как пришло.

CREATE TABLE IF NOT EXISTS category_alias (
    id              SERIAL PRIMARY KEY,
    source          VARCHAR(32) NULL,
    parent_id       INTEGER NULL REFERENCES category(id) ON DELETE CASCADE,
    alias_name      VARCHAR(255) NOT NULL,
    category_id     INTEGER NOT NULL REFERENCES category(id) ON DELETE CASCADE,
    is_auto         BOOLEAN NOT NULL DEFAULT false,
    needs_review    BOOLEAN NOT NULL DEFAULT false,
    created_at      TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_category_alias_source_parent_name UNIQUE (source, parent_id, alias_name)
);

CREATE INDEX IF NOT EXISTS idx_category_alias_lookup   ON category_alias (source, parent_id);
CREATE INDEX IF NOT EXISTS idx_category_alias_category ON category_alias (category_id);
CREATE INDEX IF NOT EXISTS idx_category_alias_review   ON category_alias (needs_review) WHERE needs_review = true;
