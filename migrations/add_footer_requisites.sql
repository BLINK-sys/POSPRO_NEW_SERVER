-- Расширяем footer_settings юридическими реквизитами + порядком колонок.
-- Реквизиты выводятся краткой строкой в подвале (юрлицо/БИН/адрес) и в
-- полном объёме на отдельной StaticPage slug='requisites'.
-- contacts_order / info_order — JSON-массивы ключей в нужном порядке.
-- NULL = дефолтный порядок (зашит во фронте).

ALTER TABLE footer_settings
    ADD COLUMN IF NOT EXISTS legal_name     VARCHAR(255),
    ADD COLUMN IF NOT EXISTS bin_number     VARCHAR(32),
    ADD COLUMN IF NOT EXISTS legal_address  VARCHAR(500),
    ADD COLUMN IF NOT EXISTS bank_name      VARCHAR(255),
    ADD COLUMN IF NOT EXISTS bank_bic       VARCHAR(32),
    ADD COLUMN IF NOT EXISTS bank_iik       VARCHAR(64),
    ADD COLUMN IF NOT EXISTS bank_kbe       VARCHAR(8),
    ADD COLUMN IF NOT EXISTS contacts_order TEXT,
    ADD COLUMN IF NOT EXISTS info_order     TEXT;
