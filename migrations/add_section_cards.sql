-- Таблицы section_cards и section_card_categories — для блока «Карточки
-- разделов» на главной. Идемпотентно.

CREATE TABLE IF NOT EXISTS section_cards (
    id                SERIAL PRIMARY KEY,
    name              VARCHAR(200) NOT NULL,
    slug              VARCHAR(220) NOT NULL UNIQUE,
    description       TEXT,
    image_url         VARCHAR(512),
    banner_image_url  VARCHAR(512),
    target            VARCHAR(20) NOT NULL DEFAULT 'link',
    link_url          VARCHAR(512),
    link_new_tab      BOOLEAN NOT NULL DEFAULT FALSE,
    "order"           INTEGER NOT NULL DEFAULT 0,
    active            BOOLEAN NOT NULL DEFAULT TRUE,
    created_at        TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at        TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS ix_section_cards_active_order
    ON section_cards (active, "order");

CREATE TABLE IF NOT EXISTS section_card_categories (
    id               SERIAL PRIMARY KEY,
    section_card_id  INTEGER NOT NULL REFERENCES section_cards(id) ON DELETE CASCADE,
    category_id      INTEGER NOT NULL REFERENCES category(id)      ON DELETE CASCADE,
    "order"          INTEGER NOT NULL DEFAULT 0,
    CONSTRAINT uq_section_card_categories_card_category
        UNIQUE (section_card_id, category_id)
);

CREATE INDEX IF NOT EXISTS ix_section_card_categories_card
    ON section_card_categories (section_card_id, "order");
